"""
CrewAI-compatible RAG tool for APOEMA agents.

Wraps RagManager.search_and_format() as a CrewAI BaseTool so AI agents
can query the pgvector-based RAG database using semantic search.
"""

import logging
from typing import Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from config import get_config

logger = logging.getLogger(__name__)


class RagSearchInput(BaseModel):
    """Input schema for ApoemaRagTool — semantic RAG search."""

    query: str = Field(..., description="The search query to find relevant documents")
    source_type: Optional[str] = Field(
        None,
        description="Optional filter by source type (e.g., 'pdf', 'json', 'csv', 'docling_json')",
    )


class ApoemaRagTool(BaseTool):
    """CrewAI tool that enables agents to perform semantic search over indexed documents."""

    name: str = "RAG Search"
    description: str = (
        "Search the RAG (Retrieval-Augmented Generation) database using semantic search. "
        "Use this to find relevant information from indexed documents such as assessment "
        "criteria, PDF reports, Docling extractions, and structured data. "
        "Provide a natural language query and optionally filter by source type."
    )
    args_schema: Type[BaseModel] = RagSearchInput

    def _run(self, query: str, source_type: Optional[str] = None) -> str:
        """
        Execute semantic search via RagManager.

        Args:
            query: Natural language search query.
            source_type: Optional source type filter (pdf, json, csv, docling_json).

        Returns:
            Formatted search results as a string (suitable for LLM context).
        """
        try:
            from rag.rag_manager import RagManager

            config = get_config()
            manager = RagManager(config)
            source_types = [source_type] if source_type else None

            return manager.search_and_format(
                query=query,
                limit=config.RAG_MAX_RESULTS,
                similarity_threshold=config.RAG_SIMILARITY_THRESHOLD,
                source_types=source_types,
                include_metadata=True,
            )
        except Exception as e:
            error_msg = f"RAG search failed: {e}"
            logger.error(error_msg)
            return error_msg

    async def _arun(self, query: str, source_type: Optional[str] = None) -> str:
        """
        Async wrapper — delegates to synchronous _run.

        Args:
            query: Natural language search query.
            source_type: Optional source type filter.

        Returns:
            Formatted search results as a string.
        """
        return self._run(query=query, source_type=source_type)

    @staticmethod
    def get_stats() -> dict:
        """
        Helper to retrieve RAG database statistics (for debugging).

        Returns:
            Dict with total_documents, total_chunks, documents_by_type, embedding_model.
        """
        try:
            from rag.rag_manager import RagManager

            config = get_config()
            manager = RagManager(config)
            return manager.get_stats()
        except Exception as e:
            logger.error(f"Failed to get RAG stats: {e}")
            return {"error": str(e)}
