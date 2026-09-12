"""Content-addressed cache for the CrewAI Knowledge index.

Indexing embeds every chunk of the assessment (plus any anexo/adendo) through the
Ollama embedder: ~13-16s per analysis, and the step that failed when ollama was
busy ("timed out in upsert", 2026-09-11). The vectors depend only on the source
CONTENT — file bytes + chunking + embedding model + library versions — so the
collection name is a digest of exactly that:

* analyses that share a source reuse the collection and skip re-embedding;
* different content lands in a different collection, which is also what keeps
  retrieval from leaking across analyses (the 2026-09-09 bug, when the
  collection was named after the agent role and every run shared one).

A collection only counts as cached when its own metadata carries the completion
marker, so a run killed mid-index (or one whose collection was wiped) is rebuilt
instead of silently serving partial retrieval.
"""

import hashlib
import json
import logging
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

logger = logging.getLogger(__name__)

MARKER_KEY = "apoema_indexed"
DOC_COUNT_KEY = "apoema_docs"
CACHE_PREFIX = "k"


def _runtime_fingerprint() -> dict:
    """Versions that can change chunking/vectorisation of the same bytes."""
    fingerprint = {}
    for package in ("crewai", "chromadb"):
        try:
            fingerprint[package] = version(package)
        except PackageNotFoundError:  # pragma: no cover - packaging oddity
            fingerprint[package] = "unknown"
    return fingerprint


def _source_fingerprint(source) -> dict:
    """Chunking parameters that change the resulting embeddings."""
    return {
        "class": type(source).__name__,
        "chunk_size": getattr(source, "content_chunk_size", None),
        "chunk_overlap": getattr(source, "content_chunk_overlap", None),
    }


def _source_paths(source) -> list:
    """Paths the source resolves its content from."""
    return [str(path) for path in (getattr(source, "file_paths", None) or [])]


def cache_key(sources, embedding_model: str) -> str:
    """Collection name for `sources`, stable while their content is unchanged.

    Hashes file BYTES rather than paths: the API stores each upload under a
    timestamped name, so a path-based key would miss on every single run. Files
    are grouped by chunking fingerprint and sorted by their own digest, which
    keeps the key independent of source order and of file names.
    """
    digest = hashlib.sha256()
    digest.update(embedding_model.encode())
    digest.update(json.dumps(_runtime_fingerprint(), sort_keys=True).encode())

    groups: dict = {}
    for source in sources:
        fingerprint = json.dumps(_source_fingerprint(source), sort_keys=True)
        file_digests = sorted(
            hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in _source_paths(source)
        )
        groups.setdefault(fingerprint, []).extend(file_digests)

    for fingerprint in sorted(groups):
        digest.update(fingerprint.encode())
        for file_digest in sorted(groups[fingerprint]):
            digest.update(file_digest.encode())

    return f"{CACHE_PREFIX}_{digest.hexdigest()[:24]}"


def _collection(knowledge, key: str):
    """The raw ChromaDB collection backing `knowledge`'s storage, or None.

    `list_collections()` is used instead of `get_collection()` on purpose: it
    returns the stored collections without resolving an embedding function (a
    lookup would download ChromaDB's default ONNX model).
    """
    try:
        client = knowledge.storage._get_client().client
        wanted = f"knowledge_{key}"
        return next((c for c in client.list_collections() if c.name == wanted), None)
    except Exception:
        return None


def is_cached(knowledge, key: str) -> bool:
    """True when `key`'s collection holds a finished, non-empty index."""
    collection = _collection(knowledge, key)
    if collection is None:
        return False
    try:
        return bool((collection.metadata or {}).get(MARKER_KEY)) and collection.count() > 0
    except Exception:
        return False


def mark_cached(knowledge, key: str) -> None:
    """Flag the collection as fully indexed.

    ChromaDB refuses to change a collection's distance function, so the
    `hnsw:*` entries must be dropped from the metadata being rewritten.
    """
    collection = _collection(knowledge, key)
    if collection is None:
        return
    try:
        metadata = {
            name: value
            for name, value in (collection.metadata or {}).items()
            if not name.startswith("hnsw:")
        }
        collection.modify(
            metadata={**metadata, MARKER_KEY: 1, DOC_COUNT_KEY: collection.count()}
        )
    except Exception as e:  # noqa: BLE001 - a missing marker only costs a rebuild
        logger.warning("Could not mark Knowledge cache %s as complete: %s", key, e)


def forget(knowledge, key: str) -> None:
    """Drop a collection so it is rebuilt from scratch (partial leftovers)."""
    try:
        knowledge.storage._get_client().delete_collection(
            collection_name=f"knowledge_{key}"
        )
    except Exception:
        pass  # nothing cached yet
