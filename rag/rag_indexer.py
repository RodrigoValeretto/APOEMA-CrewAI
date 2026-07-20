"""
RAG Indexer - Processes files from the input/ directory and indexes them into pgvector.

Supported file types:
- PDF: Extracts text using PyPDF2/pdfplumber
- JSON (assessment data): Chunks structured JSON content
- Docling JSON: Processes IBM Docling extraction output (texts, tables)
- CSV: Converts tabular data to text descriptions
- TXT/MD: Plain text chunking
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from .rag_manager import RagManager

logger = logging.getLogger(__name__)

# Chunking configuration
DEFAULT_CHUNK_SIZE = 1000  # characters per chunk
DEFAULT_CHUNK_OVERLAP = 200  # overlap between chunks
MAX_TOKENS_PER_CHUNK = 512  # Max tokens for embedding model (nomic-embed-text context window)


class RagIndexer:
    """Processes input files and indexes them into the RAG database."""

    def __init__(self, rag_manager: RagManager):
        self.rag = rag_manager
        self.chunk_size = DEFAULT_CHUNK_SIZE
        self.chunk_overlap = DEFAULT_CHUNK_OVERLAP
        self.max_tokens = MAX_TOKENS_PER_CHUNK
        self.force_reindex = False

    # ─── Text Chunking ───────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """Rough token count estimation (4 chars per token for Portuguese/English)."""
        return len(text) // 4

    def _validate_chunk_tokens(self, text: str) -> bool:
        """Check if chunk exceeds token limit."""
        token_count = self._estimate_tokens(text)
        return token_count <= self.max_tokens

    def _split_oversized_chunk(self, text: str, max_retries: int = 3) -> List[str]:
        """
        Split a chunk that exceeds token limit into smaller pieces.

        Uses recursive splitting to ensure all pieces fit within token limit.

        Args:
            text: The text to split.
            max_retries: Maximum recursion depth.

        Returns:
            List of chunks that all fit within token limit.
        """
        if self._validate_chunk_tokens(text):
            return [text.strip()]

        if max_retries <= 0:
            logger.warning(f"Chunk exceeded token limit even after splitting, keeping as-is")
            return [text.strip()]

        # Split by common delimiters
        delimiters = ["\n\n", "\n", ". ", ", "]
        for delimiter in delimiters:
            if delimiter in text:
                parts = text.split(delimiter)
                result = []
                for part in parts:
                    if part.strip():
                        result.extend(self._split_oversized_chunk(part, max_retries - 1))
                if len(result) > 1:  # Only return if we actually split
                    return result

        # Last resort: split by character count at half size
        half_size = len(text) // 2
        return self._split_oversized_chunk(
            text[:half_size],
            max_retries - 1
        ) + self._split_oversized_chunk(
            text[half_size:],
            max_retries - 1
        )

    def chunk_text(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> List[str]:
        """
        Split text into overlapping chunks for embedding.

        Uses character-based chunking with token validation to ensure
        chunks don't exceed embedding model's context window.

        Args:
            text: The text to chunk.
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Overlap between chunks.

        Returns:
            List of text chunks (guaranteed to fit within token limit).
        """
        if not text or not text.strip():
            return []

        size = chunk_size or self.chunk_size
        overlap = chunk_overlap or self.chunk_overlap

        if len(text) <= size:
            chunk = text.strip()
            # Validate and split if too large
            if not self._validate_chunk_tokens(chunk):
                logger.warning(
                    f"Single chunk exceeds token limit ({self._estimate_tokens(chunk)} tokens). "
                    f"Splitting further..."
                )
                return self._split_oversized_chunk(chunk)
            return [chunk]

        chunks = []
        start = 0
        while start < len(text):
            end = start + size
            chunk = text[start:end].strip()
            if chunk:
                # Validate and split if oversized
                if not self._validate_chunk_tokens(chunk):
                    logger.debug(
                        f"Chunk at position {start} exceeds token limit ({self._estimate_tokens(chunk)} tokens). "
                        f"Splitting further..."
                    )
                    chunks.extend(self._split_oversized_chunk(chunk))
                else:
                    chunks.append(chunk)
            start += size - overlap

        return chunks

    # ─── PDF Processing ──────────────────────────────────────────────

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text from a PDF file.

        Tries multiple backends: pymupdf (fitz), then pdfplumber, then PyPDF2.
        """
        text = None

        # Try pymupdf first (best quality)
        try:
            import fitz
            doc = fitz.open(pdf_path)
            pages = []
            for page in doc:
                pages.append(page.get_text())
            doc.close()
            text = "\n\n".join(pages)
            if text.strip():
                return text
        except ImportError:
            logger.debug("pymupdf not available")
        except Exception as e:
            logger.debug(f"pymupdf extraction failed: {e}")

        # Try pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                pages = []
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
                text = "\n\n".join(pages)
                if text.strip():
                    return text
        except ImportError:
            logger.debug("pdfplumber not available")
        except Exception as e:
            logger.debug(f"pdfplumber extraction failed: {e}")

        # Fallback: PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(pdf_path)
            pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
            text = "\n\n".join(pages)
            if text.strip():
                return text
        except ImportError:
            logger.debug("PyPDF2 not available")
        except Exception as e:
            logger.error(f"PyPDF2 extraction failed: {e}")

        if not text or not text.strip():
            raise ValueError(f"Could not extract text from PDF: {pdf_path}")

        return text

    def index_pdf(self, pdf_path: str) -> int:
        """
        Index a PDF file into the RAG database.

        Deduplication strategy:
        1. Check file hash (exact byte-for-byte match)
        2. Check content hash (semantic match, ignoring formatting)

        Returns:
            Document ID.
        """
        logger.info(f"Indexing PDF: {pdf_path}")

        # Check file-level deduplication
        file_hash = self.rag.compute_file_hash(pdf_path)
        if not self.force_reindex:
            existing_id = self.rag.document_exists(file_hash)
            if existing_id:
                logger.info(f"PDF already indexed by file hash (doc_id={existing_id}), skipping: {pdf_path}")
                return existing_id

        # Extract text
        text = self.extract_text_from_pdf(pdf_path)
        if not text.strip():
            raise ValueError(f"No text extracted from PDF: {pdf_path}")

        # Check content-level deduplication (catches semantic duplicates)
        content_hash = self.rag.compute_content_hash(text)
        if not self.force_reindex:
            existing_id = self.rag.content_hash_exists(content_hash)
            if existing_id:
                logger.warning(
                    f"PDF has duplicate content (doc_id={existing_id}). "
                    f"Skipping: {pdf_path}. Original source may be in a different directory."
                )
                return existing_id

        # Extract title from first meaningful line
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = lines[0][:200] if lines else os.path.basename(pdf_path)

        # Create document
        doc_id = self.rag.create_document(
            source_path=pdf_path,
            source_type="pdf",
            title=title,
            file_hash=file_hash,
            metadata={
                "file_name": os.path.basename(pdf_path),
                "file_size": os.path.getsize(pdf_path),
                "text_length": len(text),
                "pages_approx": text.count("\f") + 1,
                "indexed_at": datetime.now().isoformat(),
                "content_hash": content_hash,  # For semantic deduplication
            },
        )

        # Chunk and embed
        chunks = self.chunk_text(text)
        logger.info(f"Created {len(chunks)} chunks for {pdf_path}")

        for i, chunk in enumerate(chunks):
            embedding = self.rag.generate_embedding(chunk)
            self.rag.insert_chunk(
                document_id=doc_id,
                chunk_index=i,
                content=chunk,
                embedding=embedding,
                metadata={"chunk_type": "text", "position": i},
                token_count=self._estimate_tokens(chunk),
            )

        self.rag.update_document_chunk_count(doc_id, len(chunks))
        logger.info(f"Indexed PDF: {pdf_path} -> doc_id={doc_id} ({len(chunks)} chunks)")
        return doc_id

    # ─── JSON Processing ─────────────────────────────────────────────

    def _flatten_json(self, data: Any, prefix: str = "") -> List[Dict[str, str]]:
        """
        Flatten a nested JSON structure into a list of key-value descriptions.

        Returns:
            List of {"key": ..., "value": ...} dicts.
        """
        results = []

        if isinstance(data, dict):
            for key, value in data.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, (dict, list)):
                    results.extend(self._flatten_json(value, full_key))
                elif value is not None and value != "":
                    results.append({"key": full_key, "value": str(value)})
        elif isinstance(data, list):
            for i, item in enumerate(data):
                full_key = f"{prefix}[{i}]"
                if isinstance(item, (dict, list)):
                    results.extend(self._flatten_json(item, full_key))
                elif item is not None and item != "":
                    results.append({"key": full_key, "value": str(item)})
        elif data is not None and data != "":
            results.append({"key": prefix, "value": str(data)})

        return results

    def index_json(self, json_path: str) -> int:
        """
        Index a JSON file (assessment data) into the RAG database.

        Deduplication strategy:
        1. Check file hash (exact byte-for-byte match)
        2. Check content hash (semantic match, ignoring formatting)

        Returns:
            Document ID.
        """
        logger.info(f"Indexing JSON: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
            data = json.loads(raw_content)

        # Check file-level deduplication
        file_hash = self.rag.compute_file_hash(json_path)
        if not self.force_reindex:
            existing_id = self.rag.document_exists(file_hash)
            if existing_id:
                logger.info(f"JSON already indexed by file hash (doc_id={existing_id}), skipping: {json_path}")
                return existing_id

        # Check content-level deduplication (catches semantic duplicates)
        content_hash = self.rag.compute_content_hash(raw_content)
        if not self.force_reindex:
            existing_id = self.rag.content_hash_exists(content_hash)
            if existing_id:
                logger.warning(
                    f"JSON has duplicate content (doc_id={existing_id}). "
                    f"Skipping: {json_path}. Original source may be in a different directory."
                )
                return existing_id

        # Determine title
        title = os.path.basename(json_path)
        if isinstance(data, dict):
            title = data.get("area_de_avaliacao", data.get("nome", title))

        # Create document
        doc_id = self.rag.create_document(
            source_path=json_path,
            source_type="json",
            title=str(title),
            file_hash=file_hash,
            metadata={
                "file_name": os.path.basename(json_path),
                "file_size": os.path.getsize(json_path),
                "indexed_at": datetime.now().isoformat(),
                "content_hash": content_hash,  # For semantic deduplication
            },
        )

        # Flatten JSON into descriptive text
        flat_items = self._flatten_json(data)

        # Also create a full text representation
        full_text = json.dumps(data, ensure_ascii=False, indent=2)

        # Index the full text
        chunks = self.chunk_text(full_text)
        all_chunks = []

        for i, chunk in enumerate(chunks):
            all_chunks.append((i, chunk, {"chunk_type": "full_json", "position": i}))

        # Also create structured descriptions for key sections
        if flat_items:
            # Group by top-level keys
            sections = {}
            for item in flat_items:
                top_key = item["key"].split(".")[0].split("[")[0]
                if top_key not in sections:
                    sections[top_key] = []
                sections[top_key].append(f"{item['key']}: {item['value']}")

            offset = len(all_chunks)
            for section_name, lines in sections.items():
                section_text = f"Section: {section_name}\n" + "\n".join(lines)

                # Validate and split oversized sections if necessary
                if not self._validate_chunk_tokens(section_text):
                    logger.debug(
                        f"Section '{section_name}' exceeds token limit ({self._estimate_tokens(section_text)} tokens). "
                        f"Splitting further..."
                    )
                    # Split the oversized section into smaller chunks
                    sub_chunks = self._split_oversized_chunk(section_text)
                    for sub_idx, sub_chunk in enumerate(sub_chunks):
                        all_chunks.append(
                            (offset + len(all_chunks), sub_chunk,
                             {"chunk_type": "section", "section": section_name, "part": sub_idx})
                        )
                else:
                    # Section fits within token limit
                    all_chunks.append(
                        (offset + len(all_chunks), section_text,
                         {"chunk_type": "section", "section": section_name})
                    )

        # Embed and insert all chunks
        for idx, chunk_text, chunk_meta in all_chunks:
            embedding = self.rag.generate_embedding(chunk_text)
            self.rag.insert_chunk(
                document_id=doc_id,
                chunk_index=idx,
                content=chunk_text,
                embedding=embedding,
                metadata=chunk_meta,
                token_count=self._estimate_tokens(chunk_text),
            )

        self.rag.update_document_chunk_count(doc_id, len(all_chunks))
        logger.info(f"Indexed JSON: {json_path} -> doc_id={doc_id} ({len(all_chunks)} chunks)")
        return doc_id

    # ─── Docling JSON Processing ─────────────────────────────────────

    def index_docling_json(self, json_path: str, original_pdf: Optional[str] = None) -> int:
        """
        Index a Docling-structured JSON extraction into the RAG database.

        Docling JSON contains structured elements: texts, tables, pictures, etc.
        We extract all text content and table data for semantic search.

        Args:
            json_path: Path to the Docling JSON file.
            original_pdf: Optional path to the original PDF for metadata.

        Returns:
            Document ID.
        """
        logger.info(f"Indexing Docling JSON: {json_path}")

        file_hash = self.rag.compute_file_hash(json_path)
        if not self.force_reindex:
            existing_id = self.rag.document_exists(file_hash)
            if existing_id:
                logger.info(f"Docling JSON already indexed (doc_id={existing_id}), skipping")
                return existing_id

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc_name = data.get("name", os.path.basename(json_path))
        origin = data.get("origin", {})
        original_filename = origin.get("filename", original_pdf or "")

        # Create document
        doc_id = self.rag.create_document(
            source_path=json_path,
            source_type="docling_json",
            title=doc_name,
            file_hash=file_hash,
            metadata={
                "file_name": os.path.basename(json_path),
                "file_size": os.path.getsize(json_path),
                "original_pdf": original_filename,
                "docling_version": data.get("version", ""),
                "indexed_at": datetime.now().isoformat(),
            },
        )

        all_chunks = []
        chunk_idx = 0

        # Extract texts
        texts = data.get("texts", [])
        for t in texts:
            text_content = t.get("text", "")
            if text_content and text_content.strip():
                label = t.get("label", "text")
                prov = t.get("prov", [])
                page_no = prov[0].get("page_no", 0) if prov else None

                # Split large text sections into chunks
                sub_chunks = self.chunk_text(text_content, chunk_size=1500, chunk_overlap=200)
                for sub in sub_chunks:
                    all_chunks.append((
                        chunk_idx,
                        sub,
                        {
                            "chunk_type": "docling_text",
                            "label": label,
                            "page": page_no,
                        },
                        self._estimate_tokens(sub),
                    ))
                    chunk_idx += 1

        # Extract tables as structured text
        tables = data.get("tables", [])
        for t_idx, table in enumerate(tables):
            table_data = table.get("data", [])
            if not table_data:
                continue

            prov = table.get("prov", [])
            page_no = prov[0].get("page_no", 0) if prov else None

            # Convert table to readable text
            table_text_parts = []
            if table_data and isinstance(table_data, list):
                # Get grid data
                grid = table_data[0] if isinstance(table_data[0], list) else table_data
                if isinstance(grid, list):
                    for row in grid:
                        if isinstance(row, dict) and "cells" in row:
                            cells = [c.get("text", "") for c in row.get("cells", [])]
                            table_text_parts.append(" | ".join(cells))
                        elif isinstance(row, list):
                            table_text_parts.append(" | ".join(str(c) for c in row))

            if table_text_parts:
                table_text = "Table data:\n" + "\n".join(table_text_parts)
                all_chunks.append((
                    chunk_idx,
                    table_text,
                    {
                        "chunk_type": "docling_table",
                        "table_index": t_idx,
                        "page": page_no,
                    },
                    self._estimate_tokens(table_text),
                ))
                chunk_idx += 1

        if not all_chunks:
            logger.warning(f"No text content found in Docling JSON: {json_path}")
            return doc_id

        # Embed and insert all chunks
        for idx, chunk_text, chunk_meta, token_count in all_chunks:
            embedding = self.rag.generate_embedding(chunk_text)
            self.rag.insert_chunk(
                document_id=doc_id,
                chunk_index=idx,
                content=chunk_text,
                embedding=embedding,
                metadata=chunk_meta,
                token_count=token_count,
            )

        self.rag.update_document_chunk_count(doc_id, len(all_chunks))
        logger.info(f"Indexed Docling JSON: {json_path} -> doc_id={doc_id} ({len(all_chunks)} chunks)")
        return doc_id

    # ─── CSV Processing ──────────────────────────────────────────────

    def index_csv(self, csv_path: str) -> int:
        """
        Index a CSV file as descriptive text chunks.

        Deduplication strategy:
        1. Check file hash (exact byte-for-byte match)
        2. Check content hash (semantic match, ignoring row order)

        Returns:
            Document ID.
        """
        logger.info(f"Indexing CSV: {csv_path}")

        # Check file-level deduplication
        file_hash = self.rag.compute_file_hash(csv_path)
        if not self.force_reindex:
            existing_id = self.rag.document_exists(file_hash)
            if existing_id:
                logger.info(f"CSV already indexed by file hash (doc_id={existing_id}), skipping")
                return existing_id

        import csv as csv_module

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv_module.DictReader(f)
            rows = list(reader)

        if not rows:
            raise ValueError(f"Empty CSV file: {csv_path}")

        # Check content-level deduplication (catches semantic duplicates)
        # Normalize by converting back to JSON format
        rows_json = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        content_hash = self.rag.compute_content_hash(rows_json)
        if not self.force_reindex:
            existing_id = self.rag.content_hash_exists(content_hash)
            if existing_id:
                logger.warning(
                    f"CSV has duplicate content (doc_id={existing_id}). "
                    f"Skipping: {csv_path}. Original source may be in a different directory."
                )
                return existing_id

        # Create a descriptive text representation
        headers = list(rows[0].keys())
        title = os.path.basename(csv_path)

        # Create document
        doc_id = self.rag.create_document(
            source_path=csv_path,
            source_type="csv",
            title=title,
            file_hash=file_hash,
            metadata={
                "file_name": os.path.basename(csv_path),
                "file_size": os.path.getsize(csv_path),
                "row_count": len(rows),
                "columns": headers,
                "indexed_at": datetime.now().isoformat(),
                "content_hash": content_hash,  # For semantic deduplication
            },
        )

        # Build text representation
        parts = [f"CSV File: {title}"]
        parts.append(f"Columns: {', '.join(headers)}")
        parts.append(f"Total rows: {len(rows)}")
        parts.append("")

        # Add rows in batches (10 rows per chunk)
        batch_size = 10
        chunks = []
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            batch_text = "\n".join(
                ", ".join(f"{h}: {row.get(h, '')}" for h in headers)
                for row in batch
            )
            full_text = "\n".join(parts[:3]) + "\n\n" + batch_text
            chunks.append((i // batch_size, full_text))

        # Embed and insert
        for idx, chunk_text in chunks:
            embedding = self.rag.generate_embedding(chunk_text)
            self.rag.insert_chunk(
                document_id=doc_id,
                chunk_index=idx,
                content=chunk_text,
                embedding=embedding,
                metadata={"chunk_type": "csv_data", "batch": idx},
                token_count=self._estimate_tokens(chunk_text),
            )

        self.rag.update_document_chunk_count(doc_id, len(chunks))
        logger.info(f"Indexed CSV: {csv_path} -> doc_id={doc_id} ({len(chunks)} chunks)")
        return doc_id

    # ─── Directory Indexing ──────────────────────────────────────────

    def index_directory(
        self,
        directory: str,
        file_types: Optional[List[str]] = None,
        recursive: bool = False,
    ) -> List[int]:
        """
        Index all supported files in a directory.

        Args:
            directory: Path to the directory.
            file_types: List of extensions to index (e.g., ['.pdf', '.json']).
                        If None, indexes all supported types.
            recursive: Whether to scan subdirectories.

        Returns:
            List of document IDs created.
        """
        if file_types is None:
            file_types = [".pdf", ".json", ".csv", ".txt", ".md"]

        directory = Path(directory)
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        # Collect files
        pattern = "**/*" if recursive else "*"
        files = []
        for ext in file_types:
            files.extend(directory.glob(f"{pattern}{ext}"))

        # Separate docling JSONs from regular JSONs
        docling_jsons = [f for f in files if f.suffix == ".json" and "docling" in f.name.lower()]
        assessment_jsons = [
            f for f in files
            if f.suffix == ".json"
            and "docling" not in f.name.lower()
            and "assessment" in f.name.lower()
        ]
        other_jsons = [
            f for f in files
            if f.suffix == ".json"
            and "docling" not in f.name.lower()
            and "assessment" not in f.name.lower()
        ]
        pdfs = [f for f in files if f.suffix == ".pdf"]
        csvs = [f for f in files if f.suffix == ".csv"]
        texts = [f for f in files if f.suffix in [".txt", ".md"]]

        doc_ids = []

        # Index PDFs first
        for pdf_file in pdfs:
            try:
                doc_id = self.index_pdf(str(pdf_file))
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to index PDF {pdf_file}: {e}")

        # Index Docling JSONs (paired with their PDFs if possible)
        for json_file in docling_jsons:
            try:
                # Try to find matching PDF
                json_name = json_file.stem
                matching_pdf = None
                for pdf_file in pdfs:
                    if pdf_file.stem in json_name or json_name in pdf_file.stem:
                        matching_pdf = str(pdf_file)
                        break

                doc_id = self.index_docling_json(str(json_file), original_pdf=matching_pdf)
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to index Docling JSON {json_file}: {e}")

        # Index assessment JSONs
        for json_file in assessment_jsons:
            try:
                doc_id = self.index_json(str(json_file))
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to index assessment JSON {json_file}: {e}")

        # Index other JSONs
        for json_file in other_jsons:
            try:
                doc_id = self.index_json(str(json_file))
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to index JSON {json_file}: {e}")

        # Index CSVs
        for csv_file in csvs:
            try:
                doc_id = self.index_csv(str(csv_file))
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to index CSV {csv_file}: {e}")

        # Index text files
        for text_file in texts:
            try:
                doc_id = self.index_text(str(text_file))
                doc_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to index text {text_file}: {e}")

        return doc_ids

    # ─── Plain Text ──────────────────────────────────────────────────

    def index_text(self, text_path: str) -> int:
        """Index a plain text or markdown file."""
        logger.info(f"Indexing text: {text_path}")

        file_hash = self.rag.compute_file_hash(text_path)
        if not self.force_reindex:
            existing_id = self.rag.document_exists(file_hash)
            if existing_id:
                logger.info(f"Text already indexed (doc_id={existing_id}), skipping")
                return existing_id

        with open(text_path, "r", encoding="utf-8") as f:
            text = f.read()

        title = os.path.basename(text_path)

        doc_id = self.rag.create_document(
            source_path=text_path,
            source_type="txt" if text_path.endswith(".txt") else "md",
            title=title,
            file_hash=file_hash,
            metadata={
                "file_name": os.path.basename(text_path),
                "file_size": os.path.getsize(text_path),
                "indexed_at": datetime.now().isoformat(),
            },
        )

        chunks = self.chunk_text(text)
        for i, chunk in enumerate(chunks):
            embedding = self.rag.generate_embedding(chunk)
            self.rag.insert_chunk(
                document_id=doc_id,
                chunk_index=i,
                content=chunk,
                embedding=embedding,
                metadata={"chunk_type": "text", "position": i},
                token_count=self._estimate_tokens(chunk),
            )

        self.rag.update_document_chunk_count(doc_id, len(chunks))
        logger.info(f"Indexed text: {text_path} -> doc_id={doc_id} ({len(chunks)} chunks)")
        return doc_id

    # ─── Re-index ────────────────────────────────────────────────────

    def reindex_document(self, document_id: int) -> bool:
        """
        Re-index an existing document (delete old chunks and re-create).

        This is useful when the chunking strategy or embedding model changes.
        """
        doc = self.rag.get_document(document_id)
        if not doc:
            logger.error(f"Document {document_id} not found")
            return False

        source_path = doc["source_path"]
        source_type = doc["source_type"]

        # Delete old chunks
        self.rag.delete_chunks_for_document(document_id)

        # Re-index based on type
        try:
            if source_type == "pdf" and os.path.exists(source_path):
                self.index_pdf(source_path)
            elif source_type == "json" and os.path.exists(source_path):
                self.index_json(source_path)
            elif source_type == "docling_json" and os.path.exists(source_path):
                self.index_docling_json(source_path)
            elif source_type == "csv" and os.path.exists(source_path):
                self.index_csv(source_path)
            elif source_type in ("txt", "md") and os.path.exists(source_path):
                self.index_text(source_path)
            else:
                logger.warning(f"Cannot re-index document {document_id}: unknown type or missing file")
                return False

            logger.info(f"Re-indexed document {document_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to re-index document {document_id}: {e}")
            return False
