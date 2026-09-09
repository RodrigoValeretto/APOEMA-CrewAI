import os

from crewai import Agent, Task, Crew, Process, LLM
from crewai_files import PDFFile, TextFile, ImageFile
from prompt_loader import load_agent_prompt, load_task_prompt
from rag import describe_image
from retry_utils import retry_with_backoff


# Initialize LLM configuration
def get_llm(model: str = "gemini"):
    """Create and return the LLM instance.

    Supported providers (see MODEL_ALTERNATIVES_STUDY.md):
      - 'ollama': local model (OLLAMA_MODEL, default phi4-mini:3.8b)
      - 'gemini': Google Gemini Flash (GEMINI_API_KEY) — recommended, has vision
      - 'openai': OpenAI (OPENAI_API_KEY) — gpt-4o-mini, has vision
      - 'anthropic': Anthropic Claude Haiku (ANTHROPIC_API_KEY) — has vision
      - 'deepseek': DeepSeek chat (DEEPSEEK_API_KEY) — cheapest, text-only
      - 'groq': Groq Llama 3.3 70B (GROQ_API_KEY) — fastest, text-only

    Hosted providers read their API key from the environment.
    """
    if model == "ollama":
        ollama_host = os.getenv(
            "OLLAMA_HOST", os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        )
        ollama_model = os.getenv("OLLAMA_MODEL", "phi4-mini:3.8b")
        # Local models are slow (phi4-mini on CPU ≈ 3-5 tok/s), and CrewAI's
        # openai-compatible client defaults to a 600s request timeout — a task
        # needing ~2-3K output tokens would time out mid-generation and restart
        # from zero forever. Allow a generous per-request timeout for ollama.
        ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", "1800"))
        return LLM(
            model=f"ollama/{ollama_model}",
            base_url=ollama_host,
            temperature=0.4,
            timeout=ollama_timeout,
        )

    # Hosted providers: (crewai model string, env var for the API key).
    # Model names reflect the current catalog (Aug/2026) — see MODEL_ALTERNATIVES_STUDY.md.
    providers = {
        "gemini": (
            f"gemini/{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}",
            "GEMINI_API_KEY",
        ),
        "openai": ("openai/gpt-5.6-luna", "OPENAI_API_KEY"),
        "anthropic": ("anthropic/claude-haiku-4-5", "ANTHROPIC_API_KEY"),
        "deepseek": ("deepseek/deepseek-v4-flash", "DEEPSEEK_API_KEY"),
        "groq": ("groq/llama-3.3-70b-versatile", "GROQ_API_KEY"),
    }
    if model in providers:
        model_name, key_env = providers[model]
        return LLM(
            model=model_name,
            api_key=os.getenv(key_env),
            temperature=0.4,
        )

    # Unknown provider → default to gemini
    return LLM(
        model=f"gemini/{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}",
        api_key=os.getenv("GEMINI_API_KEY"),
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


def create_agents(llm, knowledge_sources=None, knowledge_collection=None):
    """Create and return all agents.

    `knowledge_sources` (CrewAI Knowledge sources, e.g. JSONKnowledgeSource) are
    attached to the data_reader agent so CrewAI automatically retrieves relevant
    chunks of the assessment file and injects them into the task prompt — the
    reliable alternative to tool-calling RAG.

    `knowledge_collection` (optional) scopes the ChromaDB collection to one
    analysis (e.g. the output prefix). CrewAI's default `set_knowledge()` names
    the collection after the agent ROLE, which is identical across analyses —
    chunks from previous runs then leak into every later analysis's retrieval
    (observed 2026-09-09: a `basic` analysis received anexo+ficha chunks from
    an older informativo run). Passing a per-analysis collection name isolates
    the knowledge base.
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
        if knowledge_collection:
            # Per-analysis collection: wipe leftovers of a previous run of the
            # SAME analysis (retry/resume) so chunks never duplicate, then index.
            from crewai.knowledge.knowledge import Knowledge

            data_reader.knowledge = Knowledge(
                sources=knowledge_sources,
                embedder=embedder,
                collection_name=knowledge_collection,
            )
            try:
                data_reader.knowledge.storage._get_client().delete_collection(
                    collection_name=f"knowledge_{knowledge_collection}"
                )
            except Exception:
                pass  # first run of this analysis: nothing to wipe
            data_reader.knowledge.add_sources()
        else:
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

    return (
        data_reader,
        summarizer,
        report_analyzer,
        utility_assessor,
        plot_data_analyst,
        plot_insights_generator,
    )


def create_tasks(output_prefix, agents, input_files, image_description="", important_programs=None):
    """Create and return all tasks with their required input files.

    `image_description` is a pre-computed visual description of the plot image,
    used only as the Ollama fallback (injected into task 7's prompt); hosted
    models receive the image natively via `input_files`.

    Only task 7's prompt contains a {plot_data} placeholder; the CSV text is
    interpolated here because text-only fallback models (ollama) receive no
    input_files, while hosted models also get the file attached via
    `input_files`.

    `important_programs` (Sigla values marked as important by the user) appends
    a "PROGRAMAS DESTACADOS" section to tasks 7-9 so the model identifies the
    highlighted programs in the plot and gives specific insights/tips about them.
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

    def _important_programs_section(important_programs):
        """PT-BR prompt section listing the user-highlighted programs."""
        if not important_programs:
            return ""
        programs = "\n".join(f"- {p}" for p in important_programs)
        return (
            "\n\nPROGRAMAS DESTACADOS (marcados como importantes pelo usuário):\n"
            f"{programs}\n\n"
            "Estes programas estão realçados no gráfico. Dê atenção especial a "
            "eles: identifique-os na visualização e nos dados, compare o "
            "desempenho de cada um com os demais programas e inclua insights, "
            "observações e sugestões específicas baseadas nos dados de cada "
            "programa destacado."
        )

    important_section = _important_programs_section(important_programs)

    (
        data_reader,
        summarizer,
        report_analyzer,
        utility_assessor,
        plot_data_analyst,
        plot_insights_generator,
    ) = agents

    # Task 1: Data Analysis
    task1_config = load_task_prompt("task1_analyze")
    task1 = Task(
        description=task1_config["description"],
        agent=data_reader,
        expected_output=task1_config["expected_output"],
        input_files={"assessment_data": input_files.get("assessment_data")},
        verbose=False,
    )

    # Task 2: Summarization
    task2_config = load_task_prompt("task2_summarize")
    task2 = Task(
        description=task2_config["description"],
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
            description=task5_config["description"],
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
    elif input_files.get("plot_data") and (
        input_files.get("plot_image") or image_description
    ):
        # Task 7: Analyze the attached PNG chart + CSV data. Hosted models
        # (gemini) receive the image natively via input_files (multimodal);
        # for 'ollama' the caller pre-computes a vision description
        # (image_description) injected as text, since CrewAI's OpenAI-compatible
        # provider does not send image files.
        task7_config = load_task_prompt("task7_plot_data_analysis")
        # Task 7 is the only prompt with a {plot_data} placeholder; the CSV
        # text is inlined because the ollama fallback strips input_files
        # (text-only model), while hosted models also receive the file natively.
        task7_desc = task7_config["description"].replace(
            "{plot_data}", plot_data_text or "(dados do CSV fornecidos acima)"
        )
        task7_desc += important_section
        if image_description:
            task7_desc += (
                "\n\nOBSERVAÇÃO: a imagem não está anexada (modelo local sem "
                "suporte multimodal). Use esta descrição visual obtida pela "
                "ferramenta de visão para a interpretação visual:\n"
                f"{image_description}"
            )
        task7_input_files: dict = {}
        if not image_description:
            # Hosted (multimodal) models: attach the CSV + PNG natively.
            # For the ollama fallback (image_description set), attaching ANY
            # input_file triggers CrewAI's supports_multimodal() gate (phi4-mini
            # is text-only) — the CSV already reaches the model via the
            # {plot_data} interpolation in the prompt instead.
            task7_input_files["plot_data"] = input_files.get("plot_data")
            if input_files.get("plot_image"):
                task7_input_files["plot_image"] = input_files["plot_image"]
        task7 = Task(
            description=task7_desc,
            agent=plot_data_analyst,
            expected_output=task7_config["expected_output"],
            name="task_7_plot_data_analysis",
            input_files=task7_input_files,
            verbose=False,
        )

        # Task 8: Generate insights and narrative from analysis
        task8_config = load_task_prompt("task8_plot_insights")
        task8 = Task(
            description=task8_config["description"] + important_section,
            agent=plot_insights_generator,
            expected_output=task8_config["expected_output"],
            markdown=True,
            output_file=f"./output/{output_prefix}_plot_insights.md",
            context=[task1, task2, task7],
            name="task_8_plot_insights",
            verbose=False,
        )

        # Task 9: Assess utility and importance of the plot
        task9_config = load_task_prompt("task9_plot_utility_importance")
        task9 = Task(
            description=task9_config["description"] + important_section,
            agent=utility_assessor,
            expected_output=task9_config["expected_output"],
            markdown=True,
            output_file=f"./output/{output_prefix}_plot_importance.md",
            context=[task1, task2, task7, task8],
            name="task_9_plot_utility_importance",
            verbose=False,
        )

        tasks.extend([task7, task8, task9])

    return tasks


def run_apoema_pipeline(
    assessment_file,
    pdf_path,
    output_prefix,
    png_path=None,
    csv_path=None,
    model="gemini",
    important_programs=None,
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
        important_programs: Program identifiers (Sigla values from the plot CSV)
            marked as important by the user; tasks 7-9 give them special focus

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

    image_description = ""
    if pdf_path:
        crew_agents.extend([report_analyzer, utility_assessor])
        input_files["report_pdf"] = PDFFile(source=pdf_path)
    elif png_path and csv_path:
        crew_agents.extend([plot_data_analyst, plot_insights_generator, utility_assessor])
        input_files["plot_data"] = TextFile(source=csv_path)
        if model == "ollama":
            # OpenAI-compatible provider can't send images; pre-compute a vision
            # description and inject it into task 7's prompt instead.
            image_description = describe_image(png_path)
        else:
            input_files["plot_image"] = ImageFile(source=png_path)

    # Create tasks with their required input files
    tasks = create_tasks(
        output_prefix,
        agents,
        input_files=input_files,
        image_description=image_description,
        important_programs=important_programs,
    )

    crew = Crew(
        agents=crew_agents,
        tasks=tasks,
        process=Process.sequential,
    )

    result = retry_with_backoff(
        crew.kickoff,
        label="crew kickoff",
    )
    return result
