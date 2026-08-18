import os

from crewai import Agent, Task, Crew, Process, LLM
from crewai_files import PDFFile, TextFile, ImageFile
from prompt_loader import load_agent_prompt, load_task_prompt
from rag import ImageDescriptionTool


# Initialize LLM configuration
def get_llm(model: str = "gemini"):
    """
    Create and return the LLM instance.
    
    Args:
        model: The model to use - 'gemini' or 'ollama' (default: 'gemini')
               - 'gemini': Google Gemini 3.5 Flash Preview
               - 'ollama': Ollama with a tool-capable model (OLLAMA_MODEL, default phi4-mini:3.8b)
    
    Returns:
        LLM: Configured LLM instance
    """
    if model == "ollama":
        ollama_host = os.getenv(
            "OLLAMA_HOST", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        ollama_model = os.getenv("OLLAMA_MODEL", "phi4-mini:3.8b")
        return LLM(
            model=f"ollama/{ollama_model}",
            base_url=ollama_host,
            temperature=0.4,
        )
    else:  # Default to gemini
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        return LLM(
            model="gemini/gemini-3-flash-preview",
            api_key=gemini_api_key,
            temperature=0.4,
        )


def get_embedder():
    """Return CrewAI's Ollama embedder config for the native Knowledge feature.

    CrewAI's `Knowledge` system chunks + embeds sources and injects the top
    relevant chunks into the task prompt automatically — no tool-calling. This
    is the reliable alternative to the removed pgvector RAG tool, whose native
    tool-calling does not execute under CrewAI's ollama provider.
    """
    ollama_host = os.getenv(
        "OLLAMA_HOST", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    return {
        "provider": "ollama",
        "config": {
            "url": f"{ollama_host}/api/embeddings",
            "model_name": os.getenv("RAG_EMBEDDING_MODEL", "nomic-embed-text"),
        },
    }


def create_agents(llm, knowledge_sources=None):
    """Create and return all agents.

    `knowledge_sources` (CrewAI Knowledge sources, e.g. JSONKnowledgeSource) are
    attached to the data_reader agent so CrewAI automatically retrieves relevant
    chunks of the assessment file and injects them into the task prompt — the
    reliable alternative to tool-calling RAG.
    """
    embedder = get_embedder()
    data_reader_config = load_agent_prompt("data_reader")
    data_reader = Agent(
        role=data_reader_config["Role"],
        goal=data_reader_config["Goal"],
        backstory=data_reader_config["Backstory"],
        llm=llm,
        knowledge_sources=knowledge_sources,
        embedder=embedder,
        verbose=False,
        multimodal=True,
    )
    # CrewAI only calls set_knowledge() during Crew.kickoff(); our Flow uses
    # task.execute_sync(), so initialize the knowledge base manually. This chunks
    # + embeds the assessment and enables auto-injection in execute_task.
    if knowledge_sources:
        data_reader.set_knowledge()

    summarizer_config = load_agent_prompt("summarizer")
    summarizer = Agent(
        role=summarizer_config["Role"],
        goal=summarizer_config["Goal"],
        backstory=summarizer_config["Backstory"],
        llm=llm,
        verbose=False,
    )

    report_analyzer_config = load_agent_prompt("report_analyzer")
    report_analyzer = Agent(
        role=report_analyzer_config["Role"],
        goal=report_analyzer_config["Goal"],
        backstory=report_analyzer_config["Backstory"],
        llm=llm,
        verbose=False,
        multimodal=True,
    )

    utility_assessor_config = load_agent_prompt("utility_assessor")
    utility_assessor = Agent(
        role=utility_assessor_config["Role"],
        goal=utility_assessor_config["Goal"],
        backstory=utility_assessor_config["Backstory"],
        llm=llm,
        verbose=False,
    )

    plot_data_analyst_config = load_agent_prompt("plot_data_analyst")
    plot_data_analyst = Agent(
        role=plot_data_analyst_config["Role"],
        goal=plot_data_analyst_config["Goal"],
        backstory=plot_data_analyst_config["Backstory"],
        llm=llm,
        verbose=False,
    )

    plot_insights_generator_config = load_agent_prompt("plot_insights_generator")
    plot_insights_generator = Agent(
        role=plot_insights_generator_config["Role"],
        goal=plot_insights_generator_config["Goal"],
        backstory=plot_insights_generator_config["Backstory"],
        llm=llm,
        verbose=False,
    )

    # Image descriptor: orchestrates the ImageDescriptionTool (which itself calls
    # the vision model). Uses the text model so tool-calling is fast and native.
    image_descriptor_config = load_agent_prompt("image_descriptor")
    image_descriptor = Agent(
        role=image_descriptor_config["Role"],
        goal=image_descriptor_config["Goal"],
        backstory=image_descriptor_config["Backstory"],
        llm=llm,
        verbose=False,
    )

    return (
        data_reader,
        summarizer,
        report_analyzer,
        utility_assessor,
        plot_data_analyst,
        plot_insights_generator,
        image_descriptor,
    )


def create_tasks(output_prefix, agents, input_files, image_description=""):
    """Create and return all tasks with their required input files.

    `image_description` is the pre-computed visual description of the plot image
    (obtained by the caller via the vision model), injected into task 7a.

    Read text file contents and interpolate the {plot_data} placeholder in the
    task prompts. CrewAI's `input_files` attach files as *multimodal*
    attachments (which text-only Ollama models ignore), so the placeholders
    would otherwise stay literal and the models would never see the actual data.
    """
    _MAX_TEXT_CHARS = 3000

    def _read_text(file_obj):
        if file_obj is None:
            return ""
        try:
            return file_obj.read_text()[: _MAX_TEXT_CHARS]
        except Exception:
            return ""

    plot_data_text = _read_text(input_files.get("plot_data"))

    def _interp(desc):
        # The assessment data is fed via CrewAI's native Knowledge feature (see
        # create_agents / ApoemaFlow) which auto-injects relevant chunks into the
        # prompt as "Additional Information" — no manual injection or tool-calling.
        desc = desc.replace("{plot_data}", plot_data_text, 1)
        desc = desc.replace("{plot_data}", "(dados do CSV fornecidos acima)")
        desc = desc.replace("{plot_image}", "")  # image handled by task 7a
        return desc

    (
        data_reader,
        summarizer,
        report_analyzer,
        utility_assessor,
        plot_data_analyst,
        plot_insights_generator,
        image_descriptor,
    ) = agents

    # Task 1: Data Analysis
    task1_config = load_task_prompt("task1_analyze")
    task1 = Task(
        description=_interp(task1_config["description"]),
        agent=data_reader,
        expected_output=task1_config["expected_output"],
        input_files={"assessment_data": input_files.get("assessment_data")},
        verbose=False,
    )

    # Task 2: Summarization
    task2_config = load_task_prompt("task2_summarize")
    task2 = Task(
        description=_interp(task2_config["description"]),
        agent=summarizer,
        expected_output=task2_config["expected_output"],
        markdown=True,
        output_file=f"./output/{output_prefix}_output.md",
        context=[task1],
        input_files={"assessment_data": input_files.get("assessment_data")},
        verbose=False,
    )

    tasks = [task1, task2]

    # Optional Tasks 3-6: Report Analysis (if PDF is available)
    if input_files.get("report_pdf"):
        # Task 3: Extract plots from PDF
        task3_config = load_task_prompt("task3_extract_plots")
        task3 = Task(
            description=task3_config["description"],
            agent=report_analyzer,
            expected_output=task3_config["expected_output"],
            input_files={"report_pdf": input_files.get("report_pdf")},
            verbose=False,
        )

        # Task 4: Analyze extracted plots
        task4_config = load_task_prompt("task4_analyze_plots")
        task4 = Task(
            description=task4_config["description"],
            agent=report_analyzer,
            expected_output=task4_config["expected_output"],
            context=[task3],
            input_files={"report_pdf": input_files.get("report_pdf")},
            verbose=False,
        )

        # Task 5: Map visualizations to CAPES criteria
        task5_config = load_task_prompt("task5_criteria_mapping")
        task5 = Task(
            description=_interp(task5_config["description"]),
            agent=report_analyzer,
            expected_output=task5_config["expected_output"],
            markdown=True,
            output_file=f"./output/{output_prefix}_conformance_report.md",
            context=[task1, task3, task4],
            input_files={
                "assessment_data": input_files.get("assessment_data"),
                "report_pdf": input_files.get("report_pdf"),
            },
            verbose=False,
        )

        # Task 6: Assess utility and assertiveness of graphics
        task6_config = load_task_prompt("task6_utility_assessment")
        task6 = Task(
            description=task6_config["description"],
            agent=utility_assessor,
            expected_output=task6_config["expected_output"],
            markdown=True,
            output_file=f"./output/{output_prefix}_utility_assessment.md",
            context=[task4, task5],
            input_files={"report_pdf": input_files.get("report_pdf")},
            verbose=False,
        )

        tasks.extend([task3, task4, task5, task6])

    # Optional Tasks 7-9: PNG + CSV Plot Analysis (if plot files are available)
    elif input_files.get("plot_image") and input_files.get("plot_data"):
        # Task 7a: Describe the PNG chart. CrewAI's ollama native tool-calling does
        # not reliably execute tools (the model emits the tool call but CrewAI does
        # not run it), so the visual description is pre-computed by the caller and
        # injected here. Task 7a then organizes that description into the
        # structured output the downstream tasks consume.
        task7a_config = load_task_prompt("task7a_describe_image")
        task7a = Task(
            description=(
                f"{task7a_config['description']}\n\n"
                f"DESCRIÇÃO VISUAL DA IMAGEM (já obtida pela ferramenta de visão):\n"
                f"{image_description}"
            ),
            agent=image_descriptor,
            expected_output=task7a_config["expected_output"],
            verbose=False,
        )

        # Task 7: Analyze PNG image and CSV data (receives vision output via context)
        task7_config = load_task_prompt("task7_plot_data_analysis")
        task7 = Task(
            description=_interp(task7_config["description"]),
            agent=plot_data_analyst,
            expected_output=task7_config["expected_output"],
            context=[task7a],
            input_files={
                "plot_data": input_files.get("plot_data"),
            },
            verbose=False,
        )

        # Task 8: Generate insights and narrative from analysis
        task8_config = load_task_prompt("task8_plot_insights")
        task8 = Task(
            description=_interp(task8_config["description"]),
            agent=plot_insights_generator,
            expected_output=task8_config["expected_output"],
            markdown=True,
            output_file=f"./output/{output_prefix}_plot_insights.md",
            context=[task1, task2, task7a, task7],
            input_files={
                "assessment_data": input_files.get("assessment_data"),
                "plot_image": input_files.get("plot_image"),
                "plot_data": input_files.get("plot_data"),
            },
            verbose=False,
        )

        # Task 9: Assess utility and importance of the plot
        task9_config = load_task_prompt("task9_plot_utility_importance")
        task9 = Task(
            description=_interp(task9_config["description"]),
            agent=utility_assessor,
            expected_output=task9_config["expected_output"],
            markdown=True,
            output_file=f"./output/{output_prefix}_plot_importance.md",
            context=[task1, task2, task7a, task7, task8],
            input_files={
                "assessment_data": input_files.get("assessment_data"),
                "plot_image": input_files.get("plot_image"),
                "plot_data": input_files.get("plot_data"),
            },
            verbose=False,
        )

        tasks.extend([task7a, task7, task8, task9])

    return tasks


def run_apoema_pipeline(
    assessment_file,
    pdf_path,
    output_prefix,
    png_path=None,
    csv_path=None,
    model="gemini",
):
    """
    Execute the APOEMA assessment analysis pipeline.

    Args:
        assessment_file: Path to the assessment data JSON file
        pdf_path: Path to optional PDF file
        output_prefix: Prefix for output files
        png_path: Path to optional PNG plot image file
        csv_path: Path to optional CSV data file
        model: Model to use - 'gemini' or 'ollama' (default: 'gemini')

    Returns:
        result: The result from crew.kickoff()
    """
    llm = get_llm(model=model)
    agents = create_agents(llm)

    # Prepare input files based on workflow type
    input_files = {"assessment_data": TextFile(source=assessment_file)}

    # Determine which agents to use
    (
        data_reader,
        summarizer,
        report_analyzer,
        utility_assessor,
        plot_data_analyst,
        plot_insights_generator,
    ) = agents
    crew_agents = [data_reader, summarizer]

    if pdf_path:
        crew_agents.extend([report_analyzer, utility_assessor])
        input_files["report_pdf"] = PDFFile(source=pdf_path)
    elif png_path and csv_path:
        crew_agents.extend([plot_data_analyst, plot_insights_generator, utility_assessor])
        input_files["plot_image"] = ImageFile(source=png_path)
        input_files["plot_data"] = TextFile(source=csv_path)

    # Create tasks with their required input files
    tasks = create_tasks(output_prefix, agents, input_files=input_files)

    crew = Crew(
        agents=crew_agents,
        tasks=tasks,
        process=Process.sequential,
    )

    result = crew.kickoff()
    return result
