import os
from crewai.flow.flow import Flow, listen, start, router, or_
from crewai_files import PDFFile, TextFile, ImageFile
from apoema_agent import (
    get_llm,
    create_agents,
    create_tasks,
)


class ApoemaFlow(Flow):
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
    ):
        super().__init__()

        # Store input configuration in state
        self.state["assessment_file"] = assessment_file
        self.state["pdf_path"] = pdf_path
        self.state["png_path"] = png_path
        self.state["csv_path"] = csv_path
        self.state["output_prefix"] = output_prefix

        # Determine which workflow path to take
        has_pdf = pdf_path and os.path.exists(pdf_path)
        has_png_csv = (
            png_path and os.path.exists(png_path) and csv_path and os.path.exists(csv_path)
        )

        self.state["workflow_type"] = "pdf" if has_pdf else ("png_csv" if has_png_csv else "basic")

        # Initialize agents for use in setup_inputs
        llm = get_llm()
        agents = create_agents(llm)

        # Create tasks once based on the workflow type
        tasks = create_tasks(
            pdf_path,
            output_prefix,
            agents,
            png_path,
            csv_path,
        )
        self.state["tasks"] = tasks
        self.state["llm"] = llm
        self.state["agents"] = agents

    @start()
    def load_input_files(self):
        """Load input files and initialize flow."""
        print("🚀 Starting APOEMA Flow...")
        print(f"Flow State ID: {self.state['id']}")
        print(f"📋 Workflow type: {self.state['workflow_type']}")
        print(f"📋 Total tasks available: {len(self.state['tasks'])}")

        print("\n📂 Loading input files...")

        input_files = {}
        input_files["assessment_data"] = TextFile(source=self.state["assessment_file"])

        if self.state["workflow_type"] == "pdf":
            input_files["report_pdf"] = PDFFile(source=self.state["pdf_path"])
            print(f"✓ PDF loaded: {os.path.basename(self.state['pdf_path'])}")
        elif self.state["workflow_type"] == "png_csv":
            input_files["plot_image"] = ImageFile(source=self.state["png_path"])
            input_files["plot_data"] = TextFile(source=self.state["csv_path"])
            print(f"✓ PNG loaded: {os.path.basename(self.state['png_path'])}")
            print(f"✓ CSV loaded: {os.path.basename(self.state['csv_path'])}")

        self.state["input_files"] = input_files

    @listen(load_input_files)
    def run_data_analysis(self):
        """Task 1: Run data analysis with the data reader agent."""
        print("\n🔍 Running data analysis...")

        tasks = self.state["tasks"]
        task1 = tasks[0]

        # Set input_files on the task
        task1.input_files = self.state["input_files"]

        result = task1.execute_sync()
        self.state["data_analysis_result"] = result
        print(f"✓ Data analysis completed")

        return result

    @listen(run_data_analysis)
    def run_summarization(self, data_analysis_result):
        """Task 2: Run summarization with the summarizer agent."""
        print("\n📝 Running summarization...")

        tasks = self.state["tasks"]
        task2 = tasks[1]
        task1 = tasks[0]

        # Set input_files and context on the task
        task2.input_files = self.state["input_files"]
        task2.context = [task1]

        result = task2.execute_sync()
        self.state["summarization_result"] = result
        print(f"✓ Summarization completed")

        return result

    @router(run_summarization)
    def route_workflow(self):
        """Router to determine the next workflow path based on workflow type."""
        workflow_type = self.state["workflow_type"]
        print(f"\n🔀 Routing workflow: {workflow_type}")
        return workflow_type

    @listen(route_workflow)
    def pdf(self):
        """Task 3-6: Process PDF if available."""
        print("\n📄 Running PDF analysis...")

        tasks = self.state["tasks"]

        # Execute PDF-related tasks (3-6)
        results = {}
        for idx, task in enumerate(tasks[2:], start=3):
            print(f"  ├─ Executing Task {idx}...")
            task.input_files = self.state["input_files"]
            result = task.execute_sync()
            results[f"task_{idx}"] = result

        self.state["pdf_analysis_results"] = results
        print(f"✓ PDF analysis completed ({len(results)} tasks)")

        return results

    @listen(route_workflow)
    def png_csv(self):
        """Task 7-9: Process PNG+CSV if available."""
        print("\n📊 Running PNG+CSV analysis...")

        tasks = self.state["tasks"]

        # Execute PNG+CSV-related tasks (7-9)
        results = {}
        for idx, task in enumerate(tasks[2:], start=7):
            print(f"  ├─ Executing Task {idx}...")
            task.input_files = self.state["input_files"]
            result = task.execute_sync()
            results[f"task_{idx}"] = result

        self.state["png_csv_analysis_results"] = results
        print(f"✓ PNG+CSV analysis completed ({len(results)} tasks)")

        return results

    @listen(route_workflow)
    def basic(self):
        """Basic workflow: only tasks 1 and 2."""
        print("\n📋 Running basic workflow (no additional analysis)")
        return None

    @listen(or_("pdf", "png_csv", "basic"))
    def finalize_flow(self, *args):
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


def run_apoema_flow(assessment_file, pdf_path, output_prefix, png_path=None, csv_path=None):
    """
    Execute the APOEMA assessment analysis pipeline using Flow.

    Args:
        assessment_file: Path to the assessment data JSON file
        pdf_path: Path to optional PDF file
        output_prefix: Prefix for output files
        png_path: Path to optional PNG plot image file
        csv_path: Path to optional CSV data file

    Returns:
        result: The result from flow.kickoff()
    """
    flow = ApoemaFlow(
        assessment_file=assessment_file,
        pdf_path=pdf_path,
        png_path=png_path,
        csv_path=csv_path,
        output_prefix=output_prefix,
    )
    result = flow.kickoff()
    return result
