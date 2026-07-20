"""
RAG Manager - Core RAG operations using PostgreSQL pgvector and Ollama embeddings.

Handles:
- Embedding generation via Ollama
- Vector similarity search via pgvector
- Document and chunk management
- Semantic search queries
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from config import Config

logger = logging.getLogger(__name__)

# Default embedding model from Ollama
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_DIM = 768


class RagManager:
    """Manages RAG operations: indexing, searching, and document management."""

    def __init__(self, config: Optional[Config] = None):
        """
        Initialize RAG Manager.

        Args:
            config: Optional Config instance. If not provided, uses the global config.
        """
        if config is None:
            from config import get_config
            config = get_config()

        self.db_host = config.DB_HOST
        self.db_port = config.DB_PORT
        self.db_user = config.DB_USER
        self.db_password = config.DB_PASSWORD
        self.db_name = config.DB_NAME
        self.ollama_base_url = config.OLLAMA_BASE_URL
        self.embedding_model = getattr(config, "RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        self.embedding_dim = getattr(config, "RAG_EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM)
        self._embedding_client = None

    def _get_connection(self):
        """Get a database connection."""
        return psycopg.connect(
            host=self.db_host,
            port=self.db_port,
            user=self.db_user,
            password=self.db_password,
            dbname=self.db_name,
        )

    def _get_embedding_client(self):
        """Lazy-load the Ollama embedding client."""
        if self._embedding_client is None:
            import ollama
            self._embedding_client = ollama.Client(host=self.ollama_base_url)
        return self._embedding_client

    # ─── Embedding Operations ────────────────────────────────────────

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate an embedding vector for the given text using Ollama.

        Args:
            text: The text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        client = self._get_embedding_client()
        try:
            response = client.embeddings(
                model=self.embedding_model,
                prompt=text,
            )
            return response["embedding"]
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a batch of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors.
        """
        embeddings = []
        for text in texts:
            embeddings.append(self.generate_embedding(text))
        return embeddings

    # ─── Document Operations ─────────────────────────────────────────

    def compute_file_hash(self, file_path: str) -> str:
        """Compute SHA256 hash of a file for deduplication."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def document_exists(self, file_hash: str) -> Optional[int]:
        """
        Check if a document with the given hash already exists.

        Returns:
            Document ID if exists, None otherwise.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM rag_documents WHERE file_hash = %s",
                        (file_hash,),
                    )
                    row = cur.fetchone()
                    return row[0] if row else None
        except psycopg.Error as e:
            logger.error(f"Failed to check document existence: {e}")
            return None

    def create_document(
        self,
        source_path: str,
        source_type: str,
        title: Optional[str] = None,
        file_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Create a new rag_documents record.

        Returns:
            Document ID.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rag_documents
                            (source_path, source_type, title, file_hash, metadata, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            source_path,
                            source_type,
                            title,
                            file_hash,
                            json.dumps(metadata or {}),
                            datetime.now(),
                            datetime.now(),
                        ),
                    )
                    doc_id = cur.fetchone()[0]
                    conn.commit()
                    logger.info(f"Created document {doc_id}: {title or source_path}")
                    return doc_id
        except psycopg.Error as e:
            logger.error(f"Failed to create document: {e}")
            raise

    def update_document_chunk_count(self, document_id: int, chunk_count: int) -> None:
        """Update the chunk count for a document."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE rag_documents
                        SET chunk_count = %s, updated_at = %s
                        WHERE id = %s
                        """,
                        (chunk_count, datetime.now(), document_id),
                    )
                    conn.commit()
        except psycopg.Error as e:
            logger.error(f"Failed to update document chunk count: {e}")

    def delete_document(self, document_id: int) -> None:
        """Delete a document and its chunks (cascade)."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM rag_documents WHERE id = %s", (document_id,))
                    conn.commit()
                    logger.info(f"Deleted document {document_id}")
        except psycopg.Error as e:
            logger.error(f"Failed to delete document: {e}")
            raise

    def get_document(self, document_id: int) -> Optional[Dict[str, Any]]:
        """Get a document by ID."""
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT * FROM rag_documents WHERE id = %s",
                        (document_id,),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None
        except psycopg.Error as e:
            logger.error(f"Failed to get document: {e}")
            return None

    def list_documents(
        self, source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List all indexed documents, optionally filtered by type."""
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    if source_type:
                        cur.execute(
                            """
                            SELECT id, source_path, source_type, title, file_hash,
                                   chunk_count, created_at
                            FROM rag_documents
                            WHERE source_type = %s
                            ORDER BY created_at DESC
                            """,
                            (source_type,),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, source_path, source_type, title, file_hash,
                                   chunk_count, created_at
                            FROM rag_documents
                            ORDER BY created_at DESC
                            """
                        )
                    return [dict(row) for row in cur.fetchall()]
        except psycopg.Error as e:
            logger.error(f"Failed to list documents: {e}")
            return []

    # ─── Chunk Operations ────────────────────────────────────────────

    def insert_chunk(
        self,
        document_id: int,
        chunk_index: int,
        content: str,
        embedding: List[float],
        embedding_model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        token_count: Optional[int] = None,
    ) -> int:
        """
        Insert a chunk with its embedding vector.

        Returns:
            Chunk ID.
        """
        # Compute content hash for deduplication
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        embedding_str = f"[{','.join(str(x) for x in embedding)}]"

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO rag_chunks
                            (document_id, chunk_index, content, content_hash,
                             embedding, embedding_model, metadata, token_count, created_at)
                        VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s, %s)
                        ON CONFLICT (document_id, chunk_index)
                        DO UPDATE SET
                            content = EXCLUDED.content,
                            content_hash = EXCLUDED.content_hash,
                            embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model,
                            metadata = EXCLUDED.metadata,
                            token_count = EXCLUDED.token_count
                        RETURNING id
                        """,
                        (
                            document_id,
                            chunk_index,
                            content,
                            content_hash,
                            embedding_str,
                            embedding_model or self.embedding_model,
                            json.dumps(metadata or {}),
                            token_count,
                            datetime.now(),
                        ),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    return row[0] if row else chunk_index
        except psycopg.Error as e:
            logger.error(f"Failed to insert chunk {chunk_index}: {e}")
            raise

    def delete_chunks_for_document(self, document_id: int) -> None:
        """Delete all chunks for a document."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM rag_chunks WHERE document_id = %s",
                        (document_id,),
                    )
                    conn.commit()
        except psycopg.Error as e:
            logger.error(f"Failed to delete chunks: {e}")

    # ─── Search Operations ───────────────────────────────────────────

    def similarity_search(
        self,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.3,
        source_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic similarity search.

        Args:
            query: The natural language query.
            limit: Maximum number of results.
            similarity_threshold: Minimum similarity score (0-1).
            source_types: Optional filter by source types (e.g., ['pdf', 'json']).

        Returns:
            List of dicts with chunk_id, document info, content, and similarity score.
        """
        # Generate embedding for the query
        query_embedding = self.generate_embedding(query)
        embedding_str = f"[{','.join(str(x) for x in query_embedding)}]"

        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    if source_types:
                        cur.execute(
                            """
                            SELECT
                                rc.id AS chunk_id,
                                rc.document_id,
                                rd.title AS document_title,
                                rd.source_path,
                                rd.source_type,
                                rc.chunk_index,
                                rc.content,
                                1 - (rc.embedding <=> %s::vector) AS similarity
                            FROM rag_chunks rc
                            JOIN rag_documents rd ON rc.document_id = rd.id
                            WHERE rd.source_type = ANY(%s)
                              AND 1 - (rc.embedding <=> %s::vector) > %s
                            ORDER BY rc.embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (
                                embedding_str,
                                source_types,
                                embedding_str,
                                similarity_threshold,
                                embedding_str,
                                limit,
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT
                                rc.id AS chunk_id,
                                rc.document_id,
                                rd.title AS document_title,
                                rd.source_path,
                                rd.source_type,
                                rc.chunk_index,
                                rc.content,
                                1 - (rc.embedding <=> %s::vector) AS similarity
                            FROM rag_chunks rc
                            JOIN rag_documents rd ON rc.document_id = rd.id
                            WHERE 1 - (rc.embedding <=> %s::vector) > %s
                            ORDER BY rc.embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (
                                embedding_str,
                                embedding_str,
                                similarity_threshold,
                                embedding_str,
                                limit,
                            ),
                        )

                    return [dict(row) for row in cur.fetchall()]
        except psycopg.Error as e:
            logger.error(f"Similarity search failed: {e}")
            return []

    def search_and_format(
        self,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.3,
        source_types: Optional[List[str]] = None,
        include_metadata: bool = True,
    ) -> str:
        """
        Search and return formatted results suitable for LLM context.

        Returns:
            Formatted string with search results.
        """
        results = self.similarity_search(
            query=query,
            limit=limit,
            similarity_threshold=similarity_threshold,
            source_types=source_types,
        )

        if not results:
            return "No relevant documents found in the RAG database."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"--- Result {i} (similarity: {r['similarity']:.2f}) ---")
            if include_metadata:
                parts.append(f"Source: {r['source_path']}")
                if r.get("document_title"):
                    parts.append(f"Document: {r['document_title']}")
                parts.append(f"Type: {r['source_type']}")
            parts.append(f"Content: {r['content']}")
            parts.append("")

        return "\n".join(parts)

    # ─── Vector Index Management ─────────────────────────────────────

    def create_vector_index(self, lists: int = 100) -> None:
        """
        Create IVFFlat index on embeddings for fast ANN search.
        Must be called after data is populated.
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # Check if index already exists
                    cur.execute(
                        """
                        SELECT 1 FROM pg_indexes
                        WHERE indexname = 'idx_rag_chunks_embedding'
                        """
                    )
                    if cur.fetchone():
                        logger.info("Vector index already exists, skipping creation.")
                        return

                    cur.execute(
                        f"""
                        CREATE INDEX idx_rag_chunks_embedding
                        ON rag_chunks
                        USING ivfflat (embedding vector_cosine_ops)
                        WITH (lists = {lists})
                        """
                    )
                    conn.commit()
                    logger.info(f"Created vector index with {lists} lists.")
        except psycopg.Error as e:
            logger.error(f"Failed to create vector index: {e}")

    # ─── Statistics ──────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get RAG database statistics."""
        try:
            with self._get_connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT COUNT(*) as count FROM rag_documents")
                    doc_count = cur.fetchone()["count"]

                    cur.execute("SELECT COUNT(*) as count FROM rag_chunks")
                    chunk_count = cur.fetchone()["count"]

                    cur.execute(
                        """
                        SELECT source_type, COUNT(*) as count
                        FROM rag_documents
                        GROUP BY source_type
                        ORDER BY count DESC
                        """
                    )
                    by_type = [dict(row) for row in cur.fetchall()]

                    return {
                        "total_documents": doc_count,
                        "total_chunks": chunk_count,
                        "documents_by_type": by_type,
                        "embedding_model": self.embedding_model,
                    }
        except psycopg.Error as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}
