"""
Tests for the APOEMA agent/task pipeline.

The assessment file is fed to agents via CrewAI's native Knowledge feature
(automatic retrieval + injection), so there is no RAG tool or pgvector index.
"""

import ast


# ─── Agent integration ─────────────────────────────────────────────


def test_create_agents_have_no_tools():
    """Agents are created without tools (Knowledge handles assessment feeding)."""
    from apoema_agent import get_llm, create_agents

    llm = get_llm(model="gemini")
    agents = create_agents(llm)
    assert len(agents) == 6
    names = {a.role for a in agents}
    assert any("Analista" in n for n in names)
    for agent in agents:
        assert agent.tools in ([], None), (
            f"Agent '{agent.role}' must not hold tools directly"
        )


def test_get_embedder_is_ollama():
    """The Knowledge embedder must use the Ollama provider + nomic-embed-text."""
    from apoema_agent import get_embedder

    embedder = get_embedder()
    assert embedder["provider"] == "ollama"
    assert embedder["config"]["model_name"] == "nomic-embed-text"


def test_get_llm_supports_multiple_providers():
    """get_llm must route every supported provider without raising.

    Providers whose native SDK is not installed (anthropic/groq need the
    `crewai[anthropic]` / `crewai[groq]` extras) are ignored; the core
    providers whose SDKs ship with the base deps must always build.
    """
    from apoema_agent import get_llm

    built = []
    for provider in ("ollama", "gemini", "openai", "anthropic", "deepseek", "groq"):
        try:
            llm = get_llm(model=provider)
            assert llm is not None, f"get_llm({provider}) returned None"
            built.append(provider)
        except ImportError:
            continue  # provider SDK not installed

    assert {"ollama", "gemini", "openai"} <= set(built)


# ─── Task wiring ───────────────────────────────────────────────────


def test_create_tasks_pdf_workflow():
    """PDF workflow yields tasks 1-6 with no RAG tool attached."""
    from apoema_agent import get_llm, create_agents, create_tasks
    from crewai_files import TextFile, PDFFile

    agents = create_agents(get_llm(model="gemini"))
    input_files = {
        "assessment_data": TextFile(source="input/cc_assessment_data.json"),
        "report_pdf": PDFFile(source="input/cc_report.pdf"),
    }
    tasks = create_tasks("test_output", agents, input_files=input_files)
    assert len(tasks) == 6
    assert all((t.tools or []) == [] for t in tasks)


def test_create_tasks_png_csv_workflow():
    """PNG+CSV workflow yields tasks 1, 2, 7, 8, 9 with no RAG tool."""
    from apoema_agent import get_llm, create_agents, create_tasks
    from crewai_files import TextFile, ImageFile

    agents = create_agents(get_llm(model="gemini"))
    input_files = {
        "assessment_data": TextFile(source="input/cc_assessment_data.json"),
        "plot_image": ImageFile(source="input/formacao-docentes.png"),
        "plot_data": TextFile(source="input/formacao-docentes.csv"),
    }
    tasks = create_tasks("test_output", agents, input_files=input_files)
    assert len(tasks) == 5
    assert all((t.tools or []) == [] for t in tasks)


# ─── Image description tool ────────────────────────────────────────


def test_image_description_tool_imports():
    """ImageDescriptionTool must import and expose the vision tool."""
    from rag import ImageDescriptionTool

    tool = ImageDescriptionTool.model_construct()
    assert tool.name == "Describe Image"
    assert "see and analyze" in tool.description.lower()


# ─── Syntax + packaging ────────────────────────────────────────────


def test_core_files_have_valid_syntax():
    """Core pipeline files must parse without syntax errors."""
    for path in [
        "apoema_agent.py",
        "apoema_flow.py",
        "rag/__init__.py",
        "rag/image_description_tool.py",
    ]:
        with open(path) as f:
            ast.parse(f.read())


def test_pyproject_toml_is_valid_syntax():
    """pyproject.toml must be valid TOML syntax."""
    import tomllib

    with open("pyproject.toml", "rb") as f:
        tomllib.load(f)
