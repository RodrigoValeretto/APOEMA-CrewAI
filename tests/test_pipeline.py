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
    # chromadb's OllamaEmbeddingFunction defaults to 60s, which a queued embed
    # outlives while ollama is still generating → "timed out in upsert".
    assert embedder["config"]["timeout"] > 60


def test_index_with_retry_degrades_instead_of_failing(monkeypatch):
    """Exhausted Knowledge indexing must not take the analysis down with it.

    It must also report the failure, so no cache marker is written for an index
    that was never built.
    """
    import apoema_agent

    def _boom(*args, **kwargs):
        raise TimeoutError("timed out in upsert")

    monkeypatch.setattr(apoema_agent, "retry_with_backoff", _boom)
    assert (
        apoema_agent._index_with_retry(lambda: None, "Knowledge indexing (probe)")
        is False
    )

    indexed = []
    monkeypatch.setattr(
        apoema_agent,
        "retry_with_backoff",
        lambda fn, **kwargs: indexed.append(fn) or fn(),
    )
    assert (
        apoema_agent._index_with_retry(lambda: "ok", "Knowledge indexing (probe)")
        is True
    )
    assert len(indexed) == 1


def test_agents_without_knowledge_sources_have_no_knowledge():
    """No sources ⇒ no Knowledge base, so no run can retrieve another's chunks."""
    from apoema_agent import get_llm, create_agents

    agents = create_agents(get_llm(model="gemini"))
    data_reader = next(a for a in agents if "Analista" in a.role)

    assert data_reader.knowledge is None


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


def test_create_tasks_injects_important_programs():
    """Important programs must be appended to tasks 7-9 descriptions."""
    from apoema_agent import get_llm, create_agents, create_tasks
    from crewai_files import TextFile, ImageFile

    agents = create_agents(get_llm(model="gemini"))
    input_files = {
        "assessment_data": TextFile(source="input/cc_assessment_data.json"),
        "plot_image": ImageFile(source="input/formacao-docentes.png"),
        "plot_data": TextFile(source="input/formacao-docentes.csv"),
    }
    tasks = create_tasks(
        "test_output",
        agents,
        input_files=input_files,
        important_programs=["UFPA-A-5-CC", "UFBA"],
    )
    assert len(tasks) == 5
    for task in tasks[2:]:  # tasks 7, 8, 9
        assert "PROGRAMAS DESTACADOS" in task.description
        assert "UFPA-A-5-CC" in task.description

    # Without important programs, no section is appended
    plain = create_tasks("test_output", agents, input_files=input_files)
    for task in plain[2:]:
        assert "PROGRAMAS DESTACADOS" not in task.description


# ─── Image description helper ──────────────────────────────────────


def test_describe_image_imports():
    """describe_image must import as a plain function and fail gracefully."""
    from rag import describe_image

    assert callable(describe_image)
    # Missing file → error string, not an exception
    assert "Error: image file not found" in describe_image("nonexistent.png")


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
