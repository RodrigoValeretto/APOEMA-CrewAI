import os
from pathlib import Path
from typing import Literal
from crewai import Crew, Process
from crewai.flow.flow import Flow, listen, start, router, or_
from crewai_files import PDFFile, TextFile, ImageFile
from crewai.tasks.task_output import TaskOutput
from apoema_agent import (
    get_llm,
    describe_image,
    create_agents,
    create_tasks,
)
from crewai.knowledge.source.json_knowledge_source import JSONKnowledgeSource
from retry_utils import (
    retry_with_backoff,
    load_checkpoint,
    save_task_checkpoint,
    completed_tasks,
    get_task_output,
    checkpoint_matches_inputs,
)


def _restore_task_output(task, key: str, raw: str) -> TaskOutput:
    """Reconstruct a TaskOutput from a checkpoint so context chains resolve."""
    return TaskOutput(
        description=task.description,
        expected_output=task.expected_output,
        name=key,
        raw=raw,
        agent=task.agent.role,
    )


class ApoemaFlow(Flow):
    stream = False  # Use synchronous execution since Dramatiq workers handle async
    verbose = False

    """
    Flow for coordinating APOEMA assessment analysis pipeline.
    Handles multiple analysis pathways:
    - PDF report analysis
    - PNG + CSV plot analysis
    - Basic assessment analysis (fallback)
    """

    def __init__(
        self,
        assessment_file="assessment_data.json",
        pdf_path=None,
        png_path=None,
        csv_path=None,
        output_prefix="output",
        model="gemini",
        important_programs=None,
        analysis_id=None,
        on_task_complete=None,
        fresh=False,
        knowledge_files=None,
    ):
        super().__init__()

        # Store input configuration in state
        self.state["assessment_file"] = assessment_file
        self.state["pdf_path"] = pdf_path
        self.state["png_path"] = png_path
        self.state["csv_path"] = csv_path
        self.state["output_prefix"] = output_prefix
        self.state["model"] = model
        self.state["important_programs"] = important_programs
        self.state["analysis_id"] = analysis_id
        self.state["fresh"] = fresh
        self.state["knowledge_files"] = knowledge_files or []

        # Store callback function
        self.on_task_complete = on_task_complete

        # Determine which workflow path to take
        has_pdf = pdf_path and os.path.exists(pdf_path)
        has_png_csv = (
            png_path and os.path.exists(png_path) and csv_path and os.path.exists(csv_path)
        )

        self.state["workflow_type"] = "pdf" if has_pdf else ("png_csv" if has_png_csv else "basic")

        # Initialize agents for use in setup_inputs
        llm = get_llm(model=model)
        # Feed the assessment file via CrewAI's native Knowledge feature: it
        # chunks + embeds the file and auto-injects the relevant chunks into the
        # data_reader's prompt (no tool-calling needed). Note: CrewAI prepends
        # "knowledge/" to string paths, so pass a Path object for absolute paths.
        # Extra converted documents (anexos/adendos de um informativo) are added
        # as further Knowledge sources so retrieval covers the whole corpus.
        knowledge_sources = None
        if os.path.exists(assessment_file):
            knowledge_sources = [JSONKnowledgeSource(file_paths=[Path(assessment_file)])]
        for extra_file in self.state["knowledge_files"]:
            if extra_file and os.path.exists(extra_file):
                if knowledge_sources is None:
                    knowledge_sources = []
                knowledge_sources.append(JSONKnowledgeSource(file_paths=[Path(extra_file)]))
        agents = create_agents(
            llm,
            knowledge_sources=knowledge_sources,
            # Per-analysis ChromaDB collection: CrewAI's default names it after
            # the agent role (constant), so chunks from previous analyses leak
            # into later retrievals (cross-analysis contamination, 2026-09-09).
            knowledge_collection=output_prefix,
        )

        # Prepare input files based on workflow type
        input_files = {"assessment_data": TextFile(source=assessment_file)}
        image_description = ""
        if self.state["workflow_type"] == "pdf":
            input_files["report_pdf"] = PDFFile(source=pdf_path)
        elif self.state["workflow_type"] == "png_csv":
            input_files["plot_data"] = TextFile(source=csv_path)
            if model == "ollama":
                # OpenAI-compatible provider can't send image files; pre-compute
                # a vision description (OLLAMA_VISION_MODEL) injected into task 7.
                image_description = describe_image(png_path)
            else:
                # Hosted (gemini): attach the chart natively — task 7 receives it
                # as multimodal content via input_files.
                input_files["plot_image"] = ImageFile(source=png_path)

        # Create tasks once with their required input files
        tasks = create_tasks(
            output_prefix,
            agents,
            input_files=input_files,
            image_description=image_description,
            important_programs=important_programs,
        )
        self.state["tasks"] = tasks
        self.state["llm"] = llm
        self.state["agents"] = agents

        # Resume support: a checkpoint for this prefix (same inputs) means a
        # previous run crashed mid-pipeline; completed tasks are restored from
        # it instead of being re-executed (and re-billed).
        checkpoint = {} if fresh else load_checkpoint(output_prefix)
        if checkpoint and not checkpoint_matches_inputs(
            checkpoint, assessment_file, png_path, csv_path
        ):
            print("ℹ️  Input files changed since the last run — ignoring checkpoint.")
            checkpoint = {}
        self.state["checkpoint"] = checkpoint

    @start()
    def run_data_analysis(self):
        """Load input files and initialize flow."""
        print("🚀 Starting APOEMA Flow...")
        print(f"Flow State ID: {self.state['id']}")
        print(f"📋 Workflow type: {self.state['workflow_type']}")
        print(f"📋 Total tasks available: {len(self.state['tasks'])}")

        """Task 1: Run data analysis with the data reader agent."""
        print("\n🔍 Running data analysis...")

        tasks = self.state["tasks"]
        task1 = tasks[0]

        if "task_1_data_analysis" in completed_tasks(self.state["checkpoint"]):
            print("↩️  Resuming: task 1 already completed — restoring from checkpoint")
            task1.output = _restore_task_output(
                task1,
                "task_1_data_analysis",
                get_task_output(self.state["checkpoint"], "task_1_data_analysis"),
            )
            result = task1.output
        else:
            result = retry_with_backoff(
                task1.execute_sync,
                label="task_1_data_analysis",
            )
            save_task_checkpoint(
                self.state["output_prefix"],
                "task_1_data_analysis",
                result.raw,
                self.state["assessment_file"],
                self.state["png_path"],
                self.state["csv_path"],
            )
        self.state["data_analysis_result"] = result
        print(f"✓ Data analysis completed")

        # Call callback if provided
        if self.on_task_complete:
            self.on_task_complete("task_1_data_analysis", str(result))

        return result

    @listen(run_data_analysis)
    def run_summarization(self):
        """Task 2: Run summarization with the summarizer agent."""
        print("\n📝 Running summarization...")

        tasks = self.state["tasks"]
        task2 = tasks[1]
        task1 = tasks[0]

        task2.context = [task1]

        if "task_2_summarization" in completed_tasks(self.state["checkpoint"]):
            print("↩️  Resuming: task 2 already completed — restoring from checkpoint")
            task2.output = _restore_task_output(
                task2,
                "task_2_summarization",
                get_task_output(self.state["checkpoint"], "task_2_summarization"),
            )
            result = task2.output
        else:
            result = retry_with_backoff(
                task2.execute_sync,
                label="task_2_summarization",
            )
            save_task_checkpoint(
                self.state["output_prefix"],
                "task_2_summarization",
                result.raw,
                self.state["assessment_file"],
                self.state["png_path"],
                self.state["csv_path"],
            )
        self.state["summarization_result"] = result
        print(f"✓ Summarization completed")

        # Call callback if provided
        if self.on_task_complete:
            self.on_task_complete("task_2_summarization", str(result))

        return result

    @router(run_summarization)
    def route_workflow(self) -> Literal["pdf", "png_csv", "basic"]:
        """Router to determine the next workflow path based on workflow type."""
        workflow_type = self.state["workflow_type"]
        print(f"\n🔀 Routing workflow: {workflow_type}")
        return workflow_type

    @listen("pdf")
    def pdf_workflow(self):
        """Task 3-6: Process PDF if available."""
        print("\n📄 Running PDF analysis...")

        tasks = self.state["tasks"]
        ckpt = self.state["checkpoint"]

        # Map task indices to task names (must match the API's task-name constants)
        task_names = {
            3: "task_3_extract_plots",
            4: "task_4_analyze_plots",
            5: "task_5_criteria_mapping",
            6: "task_6_utility_assessment",
        }

        done = completed_tasks(ckpt)

        # Execute PDF-related tasks (3-6)
        results = {}
        for idx, task in enumerate(tasks[2:], start=3):
            task_name = task_names.get(idx, f"task_{idx}")
            if task_name in done:
                print(f"↩️  Resuming: {task_name} already completed — restoring from checkpoint")
                task.output = _restore_task_output(
                    task,
                    task_name,
                    get_task_output(ckpt, task_name),
                )
                result = task.output
            else:
                print(f"  ├─ Executing Task {idx}...")
                result = retry_with_backoff(
                    task.execute_sync,
                    label=task_name,
                )
                save_task_checkpoint(
                    self.state["output_prefix"],
                    task_name,
                    result.raw,
                    self.state["assessment_file"],
                    self.state["png_path"],
                    self.state["csv_path"],
                )
            results[task_name] = result

            # Call callback if provided
            if self.on_task_complete:
                self.on_task_complete(task_name, str(result))

        self.state["pdf_analysis_results"] = results
        print(f"✓ PDF analysis completed ({len(results)} tasks)")

        return results

    @listen("png_csv")
    def png_csv_workflow(self):
        """Tasks 7-9: analyze the PNG+CSV plot via a mini-Crew (native multimodal).

        Tasks 1/2 already ran in the Flow; task8/9 read them through their
        context lists (task.output is populated), while the crew executes 7-9.
        """
        print("\n📊 Running PNG+CSV analysis...")

        task7, task8, task9 = self.state["tasks"][2:5]
        ckpt = self.state["checkpoint"]

        # Canonical task keys (must match the API's task-name constants)
        task_keys = {
            task7: "task_7_plot_data_analysis",
            task8: "task_8_plot_insights",
            task9: "task_9_plot_utility_importance",
        }

        # Restore outputs of tasks that already completed in a previous run so
        # context chains still resolve for the tasks that remain to be done.
        done = completed_tasks(ckpt)
        for task, key in task_keys.items():
            if key in done:
                task.output = _restore_task_output(task, key, get_task_output(ckpt, key))
                print(f"↩️  Resuming: {key} already completed — restoring from checkpoint")

        # Only the tasks that never completed run now (retried with backoff at
        # the crew level via retry_with_backoff below).
        pending = [t for t in task_keys if task_keys[t] not in done]

        # The plot tasks run as a Crew so input_files reach the model natively
        # (multimodal). task_callback preserves per-task progress reporting and
        # checkpoints each completed task so a crash here resumes at the next one.
        def on_task_callback(task_output):
            if self.on_task_complete:
                self.on_task_complete(task_output.name, str(task_output.raw))
            if task_output.name:
                save_task_checkpoint(
                    self.state["output_prefix"],
                    task_output.name,
                    task_output.raw,
                    self.state["assessment_file"],
                    self.state["png_path"],
                    self.state["csv_path"],
                )

        if pending:
            plot_crew = Crew(
                agents=[t.agent for t in pending],
                tasks=pending,
                process=Process.sequential,
                task_callback=on_task_callback,
            )
            retry_with_backoff(
                plot_crew.kickoff,
                label=f"png_csv mini-crew ({len(pending)} task(s))",
            )
            for task in pending:
                print(f"  ├─ Executed {task.name}")
        else:
            print("↩️  Resuming: tasks 7-9 already completed")

        # Reload the checkpoint: fresh outputs were saved by the callback during
        # kickoff, so this is now the single source of truth for all of 7-9.
        ckpt = load_checkpoint(self.state["output_prefix"])
        results = {key: get_task_output(ckpt, key) for key in task_keys.values()}

        self.state["png_csv_analysis_results"] = results
        print(f"✓ PNG+CSV analysis completed ({len(results)} tasks)")

        return results

    @listen("basic")
    def basic_workflow(self):
        """Basic workflow: only tasks 1 and 2."""
        print("\n📋 Running basic workflow (no additional analysis)")
        return None

    @listen(or_("pdf_workflow", "png_csv_workflow", "basic_workflow"))
    def finalize_flow(self):
        """Final step: Summarize flow results."""
        print("\n" + "=" * 80)
        print("✅ FLOW EXECUTION COMPLETED")
        print("=" * 80)

        print("\n📊 Flow Summary:")
        print(f"  • Workflow type: {self.state['workflow_type']}")
        print(f"  • Assessment file: {self.state['assessment_file']}")
        print(f"  • Output prefix: {self.state['output_prefix']}")

        if self.state["workflow_type"] == "pdf":
            print(f"  • PDF file: {self.state['pdf_path']}")
        elif self.state["workflow_type"] == "png_csv":
            print(f"  • PNG file: {self.state['png_path']}")
            print(f"  • CSV file: {self.state['csv_path']}")

        return self.state


def run_apoema_flow(
    assessment_file,
    pdf_path,
    output_prefix,
    png_path=None,
    csv_path=None,
    model="gemini",
    important_programs=None,
    analysis_id=None,
    on_task_complete=None,
    fresh=False,
    knowledge_files=None,
):
    """
    Execute the APOEMA assessment analysis pipeline using Flow.

    Args:
        assessment_file: Path to the assessment data JSON file
        pdf_path: Path to optional PDF file
        output_prefix: Prefix for output files (also the run id for checkpoints)
        png_path: Path to optional PNG plot image file
        csv_path: Path to optional CSV data file
        model: Model to use - 'gemini' or 'ollama' (default: 'gemini')
        important_programs: Program identifiers (Sigla values from the plot CSV)
            marked as important by the user; tasks 7-9 give them special focus
        analysis_id: Optional ID of analysis for tracking
        on_task_complete: Optional callback function(task_name, result) for each completed task
        fresh: If True, ignore any checkpoint for this prefix and re-run all tasks

    Returns:
        result: The result from flow.kickoff()
    """
    flow = ApoemaFlow(
        assessment_file=assessment_file,
        pdf_path=pdf_path,
        png_path=png_path,
        csv_path=csv_path,
        output_prefix=output_prefix,
        model=model,
        important_programs=important_programs,
        analysis_id=analysis_id,
        on_task_complete=on_task_complete,
        fresh=fresh,
        knowledge_files=knowledge_files,
    )

    flow.plot()
    result = flow.kickoff()

    return result
