"""Serialize converted documents into the enriched APOEMA JSON schema.

Two source shapes are normalized into one schema (``format``:
``apoema-json-converter-v1``):

- **PDF forms/reports** — via a Docling ``DoclingDocument`` export dict:
  blocks follow the document reading order (``body.children`` refs), keeping
  text paragraphs AND tables (with headers, structured rows and a markdown
  rendering for easy LLM consumption).
- **XLSX attachments/addenda** — via openpyxl (docling's own XLSX codec drops
  sheet names, which attachments need: ANEXO 3/4/5...). Each sheet becomes a
  ``spreadsheet`` block with its real name.

Block shapes::

    {"id": 1, "type": "text",      "page": 1, "text": "..."}
    {"id": 2, "type": "table",     "page": 3, "headers": ["A", "B"],
     "rows": [["1", "x"], ...], "markdown": "| A | B |..."}
    {"id": 3, "type": "spreadsheet", "sheet": "ANEXO 3", "rows": [...],
     "markdown": "..."}
"""
from datetime import date, datetime, time

FORMAT = "apoema-json-converter-v1"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _clean(text) -> str:
    """Normalize a cell/paragraph text for serialization."""
    if text is None:
        return ""
    return str(text).strip()


def _body_order_items(docling_dict):
    """Yield ('texts'|'tables'|'pictures', index) in document reading order."""
    body = docling_dict.get("body", {}) or {}
    for child in body.get("children", []):
        ref = (child or {}).get("$ref", "")
        parts = ref.lstrip("#/").split("/")
        if len(parts) == 2:
            yield parts[0], int(parts[1])


def _page_of(item) -> int:
    prov = item.get("prov") or []
    return int(prov[0].get("page_no", 1)) if prov else None


def _cell_text(cell) -> str:
    if isinstance(cell, dict):
        return _clean(cell.get("text"))
    if isinstance(cell, str):
        return _clean(cell)
    return ""


def _markdown_cell(value) -> str:
    """Escape a single cell for a markdown table row."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def render_markdown_table(rows, headers=None) -> str:
    """Render rows (list of lists) as a GitHub-style markdown table."""
    rows = list(rows)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    if headers:
        header = [_markdown_cell(c) for c in headers]
        header += [""] * (width - len(header))
        lines = ["| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
        body = rows
    else:
        lines = []
        body = [rows[0]] + rows[1:]  # first row acts as implicit header-less row
    for r in body:
        cells = [_markdown_cell(c) for c in r]
        cells += [""] * (width - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# PDF (docling export) -> schema
# --------------------------------------------------------------------------
def serialize_pdf_docling(
    docling_dict,
    *,
    document,
    document_type,
    corpus,
    quadrennium=None,
    sha256=None,
    tool="docling",
) -> dict:
    """Convert a DoclingDocument export dict into the enriched schema."""
    blocks = []
    for kind, idx in _body_order_items(docling_dict):
        if kind not in ("texts", "tables"):
            continue  # pictures/furniture: no text value for the pipeline
        item = docling_dict.get(kind, [])[idx]
        page = _page_of(item)
        if kind == "texts":
            text = _clean(item.get("text"))
            if not text:
                continue
            block = {"id": len(blocks) + 1, "type": "text"}
            if page:
                block["page"] = page
            block["text"] = text
            blocks.append(block)
            continue

        # table
        data = item.get("data", {}) or {}
        grid = data.get("grid") or []
        # Headers = leading rows flagged column_header by the table model
        headers = []
        rows = []
        for row in grid:
            cells = [_cell_text(c) for c in row]
            if all(
                isinstance(c, dict) and c.get("column_header") for c in row if c is not None
            ) and not headers and len(row) > 0 and all(c is not None for c in row):
                headers = cells
            else:
                rows.append(cells)
        # drop spacer rows (empty everywhere)
        rows = [r for r in rows if any(c for c in r)]
        if not rows and not headers:
            continue
        block = {"id": len(blocks) + 1, "type": "table"}
        if page:
            block["page"] = page
        if headers:
            block["headers"] = headers
        block["rows"] = rows
        block["markdown"] = render_markdown_table(rows, headers or None)
        blocks.append(block)

    source = {"file_format": "pdf"}
    if sha256:
        source["sha256"] = sha256
    return _wrap(blocks, source, document, document_type, corpus, quadrennium, tool)


# --------------------------------------------------------------------------
# XLSX (openpyxl) -> schema
# --------------------------------------------------------------------------
def _xlsx_value(value):
    """Normalize a spreadsheet cell value for JSON."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def serialize_xlsx(path, *, document, document_type, corpus, quadrennium=None,
                   sha256=None, tool="openpyxl") -> dict:
    """Convert an XLSX workbook into spreadsheet blocks (one per sheet)."""
    from openpyxl import load_workbook

    blocks = []
    sheets = []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            sheets.append(ws.title)
            rows = []
            for row in ws.iter_rows(values_only=True):
                values = [_xlsx_value(v) for v in row]
                # trim trailing empty cells, drop fully-empty rows
                while values and values[-1] in ("", None):
                    values.pop()
                if any(v not in ("", None) for v in values):
                    rows.append(["" if v is None else v for v in values])
            if not rows:
                continue
            blocks.append(
                {
                    "id": len(blocks) + 1,
                    "type": "spreadsheet",
                    "sheet": ws.title,
                    "rows": rows,
                    "markdown": render_markdown_table(rows),
                }
            )
    finally:
        wb.close()

    source = {"file_format": "xlsx", "sheets": sheets}
    if sha256:
        source["sha256"] = sha256
    return _wrap(blocks, source, document, document_type, corpus, quadrennium, tool)


# --------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------
def _wrap(blocks, source, document, document_type, corpus, quadrennium, tool) -> dict:
    from datetime import datetime, timezone

    return {
        "format": FORMAT,
        "document_type": document_type,
        "document": document,
        "corpus": corpus,
        "quadrennium": quadrennium,
        "source": source,
        "conversion": {
            "tool": tool,
            "converted_at": datetime.now(timezone.utc).isoformat(),
        },
        "blocks": blocks,
    }
