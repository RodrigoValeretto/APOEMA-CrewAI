"""Tests for the content-addressed Knowledge cache (knowledge_cache).

The cache key decides two things at once: which ChromaDB collection a set of
sources is embedded into (isolation — different content must never share a
collection, the 2026-09-09 leak) and whether the embed can be skipped (analyses
sharing a source reuse the collection).
"""

from pathlib import Path

from knowledge_cache import (
    DOC_COUNT_KEY,
    MARKER_KEY,
    cache_key,
    forget,
    is_cached,
    mark_cached,
)

MODEL = "nomic-embed-text"


class _Source:
    """Minimal stand-in for a CrewAI Knowledge source."""

    def __init__(self, *paths, chunk_size=None, chunk_overlap=None):
        self.file_paths = [Path(path) for path in paths]
        self.content_chunk_size = chunk_size
        self.content_chunk_overlap = chunk_overlap


class _Collection:
    def __init__(self, name, metadata=None, docs=0):
        self.name = name
        self.metadata = metadata or {}
        self.docs = docs

    def count(self):
        return self.docs

    def modify(self, metadata):
        self.metadata = metadata


class _RawClient:
    def __init__(self, collections):
        self.collections = collections

    def list_collections(self):
        return list(self.collections)


class _Client:
    """The CrewAI-side client wrapper: raw chromadb client + collection ops."""

    def __init__(self, collections):
        self.client = _RawClient(collections)
        self.deleted = []

    def delete_collection(self, collection_name):
        self.deleted.append(collection_name)


class _Knowledge:
    def __init__(self, client):
        self.storage = type("_Storage", (), {"_get_client": lambda _self: client})()


def _file(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ─── cache_key ──────────────────────────────────────────────────


def test_cache_key_ignores_file_names(tmp_path):
    """The API stores each upload under a timestamped name — same bytes, same key."""
    first = _file(tmp_path, "20260911_111407_cc.json", '{"area": "CC"}')
    second = _file(tmp_path, "20260911_231518_cc.json", '{"area": "CC"}')

    assert cache_key([_Source(first)], MODEL) == cache_key([_Source(second)], MODEL)


def test_cache_key_changes_with_content(tmp_path):
    """Different content must land in a different collection (isolation)."""
    first = _file(tmp_path, "a.json", '{"area": "CC"}')
    second = _file(tmp_path, "b.json", '{"area": "ADM"}')

    assert cache_key([_Source(first)], MODEL) != cache_key([_Source(second)], MODEL)


def test_cache_key_changes_with_embedding_model(tmp_path):
    """A different embedder invalidates the vectors."""
    source = _file(tmp_path, "a.json", '{"area": "CC"}')

    assert cache_key([_Source(source)], "nomic-embed-text") != cache_key(
        [_Source(source)], "other-embedder"
    )


def test_cache_key_changes_with_chunking(tmp_path):
    """Chunking changes the chunks, hence the vectors."""
    source = _file(tmp_path, "a.json", '{"area": "CC"}')

    assert cache_key([_Source(source, chunk_size=1000)], MODEL) != cache_key(
        [_Source(source, chunk_size=500)], MODEL
    )


def test_cache_key_ignores_source_order(tmp_path):
    """The source set is unordered: (assessment, anexo) == (anexo, assessment)."""
    assessment = _file(tmp_path, "a.json", '{"area": "CC"}')
    anexo = _file(tmp_path, "b.json", '{"producao": []}')

    assert cache_key([_Source(assessment), _Source(anexo)], MODEL) == cache_key(
        [_Source(anexo), _Source(assessment)], MODEL
    )


def test_cache_key_is_a_valid_collection_name(tmp_path):
    """CrewAI prefixes `knowledge_`; ChromaDB caps names at 63 chars."""
    key = cache_key([_Source(_file(tmp_path, "a.json", "{}"))], MODEL)

    assert key[0].isalnum() and key.replace("_", "").isalnum()
    assert len(f"knowledge_{key}") <= 63


# ─── is_cached / mark_cached / forget ───────────────────────────────


def test_is_cached_requires_marker_and_documents():
    key = "k_abc"
    marked = _Collection(f"knowledge_{key}", {MARKER_KEY: 1}, docs=7)
    unmarked = _Collection(f"knowledge_{key}", {"hnsw:space": "cosine"}, docs=7)
    empty = _Collection(f"knowledge_{key}", {MARKER_KEY: 1}, docs=0)

    assert is_cached(_Knowledge(_Client([marked])), key) is True
    assert is_cached(_Knowledge(_Client([unmarked])), key) is False
    # A run killed mid-index (or wiped vectors) must not be served.
    assert is_cached(_Knowledge(_Client([empty])), key) is False
    assert is_cached(_Knowledge(_Client([])), key) is False


def test_mark_cached_keeps_metadata_but_drops_hnsw_params():
    """ChromaDB refuses a metadata rewrite that includes the distance function."""
    key = "k_abc"
    collection = _Collection(f"knowledge_{key}", {"hnsw:space": "cosine"}, docs=5)

    mark_cached(_Knowledge(_Client([collection])), key)

    assert collection.metadata == {MARKER_KEY: 1, DOC_COUNT_KEY: 5}


def test_forget_deletes_the_backing_collection():
    key = "k_abc"
    client = _Client([_Collection(f"knowledge_{key}", {}, docs=1)])

    forget(_Knowledge(client), key)

    assert client.deleted == [f"knowledge_{key}"]


def test_forget_is_quiet_when_nothing_is_cached():
    """Deleting a missing collection must not break the rebuild path."""
    forget(_Knowledge(_Client([])), "k_missing")
