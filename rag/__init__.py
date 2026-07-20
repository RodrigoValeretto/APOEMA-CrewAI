"""
RAG (Retrieval-Augmented Generation) package for APOEMA-CrewAI.

Uses PostgreSQL with pgvector for vector storage and Ollama for embeddings.
Provides a CrewAI-compatible tool for agent integration.
"""

from .rag_manager import RagManager
from .rag_indexer import RagIndexer
from .crewai_rag_tool import ApoemaRagTool

__all__ = ["RagManager", "RagIndexer", "ApoemaRagTool"]
