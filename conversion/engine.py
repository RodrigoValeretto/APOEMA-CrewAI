"""Conversion engine: source file (PDF/XLSX) -> enriched JSON schema.

Heavy imports (docling/torch) are done lazily inside the functions so that
importing this module is cheap — the analysis workers and the API never load
torch unless a conversion actually runs (dedicated ``conversion`` queue).
"""
import hashlib
from pathlib import Path

from .serialize import serialize_pdf_docling, serialize_xlsx


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _version(dist: str) -> str:
    try:
        from importlib.metadata import version

        return version(dist)
    except Exception:
        return "?"


def convert_source_file(
    source_path,
    *,
    kind,
    informativo,
    quadrienio=None,
    do_ocr=False,
) -> dict:
    """Convert one source file into the enriched JSON schema.

    Args:
        source_path: path to the PDF or XLSX file
        kind: ficha | anexo | adendo (``tipo_documento`` in the output)
        informativo: informativo slug (e.g. ``ciencia_da_computacao``)
        quadrienio: optional CAPES quadrennium label (e.g. "2025-2028")
        do_ocr: run OCR on PDFs (default False — CAPES fichas have a text layer
            and docling's default OCR model download is not always reachable)

    Returns:
        Enriched JSON dict (see conversion.serialize).
    """
    path = Path(source_path)
    ext = path.suffix.lower()
    sha = sha256_of(path)
    common = dict(
        documento=path.name,
        tipo_documento=kind,
        informativo=informativo,
        quadrienio=quadrienio,
        sha256=sha,
    )
    if ext == ".pdf":
        return _convert_pdf(path, do_ocr=do_ocr, **common)
    if ext == ".xlsx":
        return serialize_xlsx(
            path, ferramenta=f"openpyxl {_version('openpyxl')}", **common
        )
    raise ValueError(f"Unsupported source extension for conversion: {ext!r}")


def _convert_pdf(path, *, do_ocr, **common) -> dict:
    """Lazy docling conversion of a text-layer PDF into the enriched schema."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = do_ocr
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(str(path))
    export = result.document.export_to_dict()
    return serialize_pdf_docling(
        export,
        ferramenta=f"docling {_version('docling')}",
        **common,
    )
