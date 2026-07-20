#!/usr/bin/env python3
"""
APOEMA RAG Indexer CLI

Indexes all files from the input/ directory into the pgvector RAG database.

Usage:
    # Index all supported files from the default input/ directory
    python scripts/index_rag.py

    # Index a specific file
    python scripts/index_rag.py --file input/cc_report.pdf

    # Index a specific directory
    python scripts/index_rag.py --dir input/

    # Index with custom chunk size
    python scripts/index_rag.py --chunk-size 800 --chunk-overlap 150

    # Re-index a specific document by ID
    python scripts/index_rag.py --reindex 3

    # Show RAG statistics
    python scripts/index_rag.py --stats

    # List indexed documents
    python scripts/index_rag.py --list

    # Force re-indexing of all files (skip deduplication)
    python scripts/index_rag.py --force
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import RagManager, RagIndexer
from config import get_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("index_rag")


def setup_parser() -> argparse.ArgumentParser:
    """Configure argument parser."""
    parser = argparse.ArgumentParser(
        description="APOEMA RAG Indexer - Index documents into the pgvector database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--file", "-f",
        type=str,
        help="Index a specific file",
    )
    group.add_argument(
        "--dir", "-d",
        type=str,
        default=None,
        help="Index all files in a directory (default: input/)",
    )
    group.add_argument(
        "--reindex", "-r",
        type=int,
        help="Re-index an existing document by ID",
    )
    group.add_argument(
        "--stats", "-s",
        action="store_true",
        help="Show RAG database statistics",
    )
    group.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all indexed documents",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-indexing even if document is already indexed",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Override default chunk size (default: 1000)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help="Override default chunk overlap (default: 200)",
    )
    parser.add_argument(
        "--create-vector-index",
        action="store_true",
        help="Create IVF flat vector index for faster searches (run after indexing)",
    )
    parser.add_argument(
        "--search",
        type=str,
        metavar="QUERY",
        help="Perform a test search after indexing",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subdirectories",
    )

    return parser


def index_single_file(file_path: str, indexer: RagIndexer) -> bool:
    """Index a single file based on its extension."""
    ext = Path(file_path).suffix.lower()
    file_name = Path(file_path).name.lower()

    try:
        if ext == ".pdf":
            indexer.index_pdf(file_path)
        elif ext == ".json" and "docling" in file_name:
            indexer.index_docling_json(file_path)
        elif ext == ".json":
            indexer.index_json(file_path)
        elif ext == ".csv":
            indexer.index_csv(file_path)
        elif ext in (".txt", ".md"):
            indexer.index_text(file_path)
        else:
            logger.warning(f"Unsupported file type: {file_path}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to index {file_path}: {e}")
        return False


def main():
    """Main entry point."""
    parser = setup_parser()
    args = parser.parse_args()

    config = get_config()
    rag_manager = RagManager(config=config)
    indexer = RagIndexer(rag_manager)

    # Configure chunking
    if args.chunk_size:
        indexer.chunk_size = args.chunk_size
    else:
        indexer.chunk_size = config.RAG_CHUNK_SIZE

    if args.chunk_overlap:
        indexer.chunk_overlap = args.chunk_overlap
    else:
        indexer.chunk_overlap = config.RAG_CHUNK_OVERLAP

    # Configure force re-indexing
    indexer.force_reindex = args.force

    # ─── Action: Stats ──────────────────────────────────────────
    if args.stats:
        stats = rag_manager.get_stats()
        print("\n=== RAG Database Statistics ===")
        print(f"  Total Documents: {stats.get('total_documents', 0)}")
        print(f"  Total Chunks:    {stats.get('total_chunks', 0)}")
        print(f"  Embedding Model: {stats.get('embedding_model', 'unknown')}")
        print("\n  Documents by Type:")
        for entry in stats.get("documents_by_type", []):
            print(f"    {entry['source_type']}: {entry['count']}")
        return

    # ─── Action: List ───────────────────────────────────────────
    if args.list:
        docs = rag_manager.list_documents()
        if not docs:
            print("No documents indexed yet.")
            return

        print(f"\n=== Indexed Documents ({len(docs)} total) ===\n")
        for doc in docs:
            print(f"  ID: {doc['id']}")
            print(f"  Title: {doc.get('title', 'N/A')}")
            print(f"  Type: {doc['source_type']}")
            print(f"  Path: {doc['source_path']}")
            print(f"  Chunks: {doc.get('chunk_count', 0)}")
            print(f"  Indexed: {doc.get('created_at', 'unknown')}")
            print()
        return

    # ─── Action: Re-index ───────────────────────────────────────
    if args.reindex:
        doc_id = args.reindex
        print(f"\nRe-indexing document {doc_id}...")
        success = indexer.reindex_document(doc_id)
        if success:
            print(f"✓ Document {doc_id} re-indexed successfully.")
        else:
            print(f"✗ Failed to re-index document {doc_id}.")
        return

    # ─── Action: Index File ─────────────────────────────────────
    if args.file:
        file_path = args.file
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            sys.exit(1)

        print(f"\nIndexing single file: {file_path}")
        success = index_single_file(file_path, indexer)
        if success:
            print(f"✓ File indexed successfully.")
        else:
            print(f"✗ Failed to index file.")
        return

    # ─── Action: Index Directory (default) ──────────────────────
    directory = args.dir or config.RAG_INPUT_DIR
    if not os.path.exists(directory):
        print(f"Error: Directory not found: {directory}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"APOEMA RAG Indexer")
    print(f"{'='*60}")
    print(f"Directory: {directory}")
    print(f"Chunk size: {indexer.chunk_size}")
    print(f"Chunk overlap: {indexer.chunk_overlap}")
    print(f"Embedding model: {rag_manager.embedding_model}")
    print(f"{'='*60}\n")

    # Index directory
    try:
        doc_ids = indexer.index_directory(
            directory=directory,
            recursive=args.recursive,
        )
        print(f"\n{'='*60}")
        print(f"Indexing complete!")
        print(f"Documents indexed: {len(doc_ids)}")
        print(f"Document IDs: {doc_ids}")
        print(f"{'='*60}")

        # Create vector index after bulk indexing
        if args.create_vector_index:
            print("\nCreating vector similarity index for faster searches...")
            rag_manager.create_vector_index()
            print("✓ Vector index created.")

        # Show stats
        stats = rag_manager.get_stats()
        print(f"\nDatabase stats: {stats['total_documents']} documents, "
              f"{stats['total_chunks']} chunks")

    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        print(f"\n✗ Indexing failed: {e}")
        sys.exit(1)

    # ─── Optional Test Search ───────────────────────────────────
    if args.search:
        print(f"\n{'='*60}")
        print(f"Test Search: \"{args.search}\"")
        print(f"{'='*60}\n")
        results = rag_manager.search_and_format(query=args.search)
        print(results)


if __name__ == "__main__":
    main()
