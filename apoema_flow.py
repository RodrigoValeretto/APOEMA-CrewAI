import os
from typing import Literal
from crewai.flow.flow import Flow, listen, start, router, or_
from crewai_files import PDFFile, TextFile, ImageFile
from apoema_agent import (
    get_llm,
    create_agents,
    create_tasks,
)


class ApoemaFlow(Flow):
    stream = True
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
        analysis_id=None,
        on_task_complete=None,
    ):
        super().__init__()

        # Store input configuration in state
        self.state["assessment_file"] = assessment_file
        self.state["pdf_path"] = pdf_path
        self.state["png_path"] = png_path
        self.state["csv_path"] = csv_path
        self.state["output_prefix"] = output_prefix
        self.state["model"] = model
        self.state["analysis_id"] = analysis_id

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
        agents = create_agents(llm)

        # Prepare input files based on workflow type
        input_files = {"assessment_data": TextFile(source=assessment_file)}
        if self.state["workflow_type"] == "pdf":
            input_files["report_pdf"] = PDFFile(source=pdf_path)
        elif self.state["workflow_type"] == "png_csv":
            input_files["plot_image"] = ImageFile(source=png_path)
            input_files["plot_data"] = TextFile(source=csv_path)

        # Create tasks once with their required input files
        tasks = create_tasks(
            output_prefix,
            agents,
            input_files=input_files,
        )
        self.state["tasks"] = tasks
        self.state["llm"] = llm
        self.state["agents"] = agents

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

        result = task1.execute_sync()
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

        result = task2.execute_sync()
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

        # Map task indices to task names
        task_names = {
            3: "task_3_extract_plots",
            4: "task_4_analyze_plots",
            5: "task_5_criteria_mapping",
            6: "task_6_utility_assessment",
        }

        # Execute PDF-related tasks (3-6)
        results = {}
        for idx, task in enumerate(tasks[2:], start=3):
            print(f"  ├─ Executing Task {idx}...")
            result = task.execute_sync()
            results[f"task_{idx}"] = result

            # Call callback if provided
            if self.on_task_complete:
                task_name = task_names.get(idx, f"task_{idx}")
                self.on_task_complete(task_name, str(result))

        self.state["pdf_analysis_results"] = results
        print(f"✓ PDF analysis completed ({len(results)} tasks)")

        return results

    @listen("png_csv")
    def png_csv_workflow(self):
        """Task 7-9: Process PNG+CSV if available."""
        print("\n📊 Running PNG+CSV analysis...")

        tasks = self.state["tasks"]

        # Map task indices to task names
        task_names = {
            7: "task_7_plot_data_analysis",
            8: "task_8_plot_insights",
            9: "task_9_plot_utility_importance",
        }

        # Execute PNG+CSV-related tasks (7-9)
        results = {}
        for idx, task in enumerate(tasks[2:], start=7):
            print(f"  ├─ Executing Task {idx}...")
            result = task.execute_sync()
            results[f"task_{idx}"] = result

            # Call callback if provided
            if self.on_task_complete:
                task_name = task_names.get(idx, f"task_{idx}")
                self.on_task_complete(task_name, str(result))

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


async def run_apoema_flow(
    assessment_file,
    pdf_path,
    output_prefix,
    png_path=None,
    csv_path=None,
    model="gemini",
    analysis_id=None,
    on_task_complete=None,
):
    """
    Execute the APOEMA assessment analysis pipeline using Flow.

    Args:
        assessment_file: Path to the assessment data JSON file
        pdf_path: Path to optional PDF file
        output_prefix: Prefix for output files
        png_path: Path to optional PNG plot image file
        csv_path: Path to optional CSV data file
        model: Model to use - 'gemini' or 'ollama' (default: 'gemini')
        analysis_id: Optional ID of analysis for tracking
        on_task_complete: Optional callback function(task_name, result) for each completed task

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
        analysis_id=analysis_id,
        on_task_complete=on_task_complete,
    )

    flow.plot()
    streaming = flow.kickoff_async()

    async for chunk in await streaming:
        print("Processing....", end="\n", flush=True)

    return streaming.result
