"""
Tests for the RAG module — validates imports, config, tool interface, and chunking.
"""

import os
import sys
import ast


# ─── Syntax validation ────────────────────────────────────────────

RAG_FILES = [
    "rag/__init__.py",
    "rag/rag_manager.py",
    "rag/rag_indexer.py",
    "rag/crewai_rag_tool.py",
    "scripts/index_rag.py",
]


def test_all_rag_files_have_valid_syntax():
    """Every new RAG file must parse without syntax errors."""
    for path in RAG_FILES:
        with open(path) as f:
            ast.parse(f.read())  # raises SyntaxError on failure


# ─── Import validation ─────────────────────────────────────────────

def test_rag_package_imports():
    """RAG package must export the three public classes."""
    from rag import RagManager, RagIndexer, ApoemaRagTool
    assert RagManager is not None
    assert RagIndexer is not None
    assert ApoemaRagTool is not None


def test_rag_manager_imports_in_isolation():
    """RagManager must import without side effects."""
    from rag.rag_manager import RagManager
    assert RagManager is not None


def test_rag_indexer_imports_in_isolation():
    """RagIndexer must import without side effects."""
    from rag.rag_indexer import RagIndexer
    assert RagIndexer is not None


def test_crewai_rag_tool_imports_in_isolation():
    """ApoemaRagTool must import without side effects."""
    from rag.crewai_rag_tool import ApoemaRagTool
    assert ApoemaRagTool is not None


def test_cli_script_is_valid_python():
    """The indexing CLI script must be valid Python."""
    from importlib.machinery import SourceFileLoader
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "index_rag", "scripts/index_rag.py"
    )
    assert spec is not None


# ─── Config validation ─────────────────────────────────────────────

def test_config_has_rag_settings():
    """Config must expose all RAG-related settings."""
    from config import Config
    c = Config()
    assert c.RAG_EMBEDDING_MODEL == "nomic-embed-text"
    assert c.RAG_EMBEDDING_DIM == 768
    assert c.RAG_SIMILARITY_THRESHOLD == 0.3
    assert c.RAG_MAX_RESULTS == 5
    assert c.RAG_CHUNK_SIZE == 1000
    assert c.RAG_CHUNK_OVERLAP == 200
    assert c.RAG_INPUT_DIR.endswith("input")


# ─── Tool interface validation ─────────────────────────────────────

def test_apoema_rag_tool_schema():
    """ApoemaRagTool must have valid name, description, and args_schema."""
    from rag.crewai_rag_tool import ApoemaRagTool, RagSearchInput

    # model_construct skips __init__ (avoids DB connection) but sets fields
    tool = ApoemaRagTool.model_construct()
    assert tool.name == "RAG Search"
    assert "semantic search" in tool.description.lower()
    assert tool.args_schema is RagSearchInput


def test_rag_search_input_fields():
    """RagSearchInput must require query and accept optional source_type."""
    from rag.crewai_rag_tool import RagSearchInput

    schema = RagSearchInput.model_json_schema()
    required = schema.get("required", [])
    assert "query" in required
    assert "source_type" in schema.get("properties", {})


# ─── Chunking logic ────────────────────────────────────────────────

def test_chunk_text_short_input():
    """Short text must return a single chunk."""
    from rag.rag_indexer import RagIndexer
    from rag.rag_manager import RagManager

    indexer = RagIndexer(RagManager.__new__(RagManager))
    chunks = indexer.chunk_text("Short text.", chunk_size=50)
    assert len(chunks) == 1
    assert chunks[0] == "Short text."


def test_chunk_text_long_input():
    """Long text must split into overlapping chunks."""
    from rag.rag_indexer import RagIndexer
    from rag.rag_manager import RagManager

    indexer = RagIndexer(RagManager.__new__(RagManager))
    text = "word " * 100
    chunks = indexer.chunk_text(text, chunk_size=50, chunk_overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 50


def test_chunk_text_empty_input():
    """Empty text must return an empty list."""
    from rag.rag_indexer import RagIndexer
    from rag.rag_manager import RagManager

    indexer = RagIndexer(RagManager.__new__(RagManager))
    assert indexer.chunk_text("") == []
    assert indexer.chunk_text("   ") == []


# ─── Agent integration ─────────────────────────────────────────────

def test_create_agents_without_rag():
    """Agents must be creatable with RAG disabled (CI/dev without DB)."""
    from apoema_agent import get_llm, create_agents

    llm = get_llm(model="gemini")
    agents = create_agents(llm, enable_rag=False)
    assert len(agents) == 6
    names = {a.role for a in agents}
    assert any("Analista" in n for n in names)  # at least one Analista role
    assert any("Estrategista" in n or "Avaliador" in n for n in names)


def test_create_agents_with_rag():
    """Agents must be creatable with RAG enabled (graceful fallback)."""
    from apoema_agent import get_llm, create_agents

    llm = get_llm(model="gemini")
    agents = create_agents(llm, enable_rag=True)
    assert len(agents) == 6
    # RAG tool may or may not be attached depending on DB availability,
    # but agent creation must never crash.
