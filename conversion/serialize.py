"""Serialize converted documents into the enriched APOEMA JSON schema.

Two source shapes are normalized into one schema (``formato``:
``apoema-json-converter-v1``):

- **PDF fichas/relatórios** — via a Docling ``DoclingDocument`` export dict:
  blocks follow the document reading order (``body.children`` refs), keeping
  text paragraphs AND tables (with headers, structured rows and a markdown
  rendering for easy LLM consumption).
- **XLSX anexos/adendos** — via openpyxl (docling's own XLSX codec drops sheet
  names, which anexos need: ANEXO 3/4/5...). Each sheet becomes a
  ``planilha`` block with its real name.

Block shapes::

    {"id": 1, "tipo": "texto",    "pagina": 1, "texto": "..."}
    {"id": 2, "tipo": "tabela",   "pagina": 3, "cabecalhos": ["A", "B"],
     "linhas": [["1", "x"], ...], "markdown": "| A | B |..."}
    {"id": 3, "tipo": "planilha", "aba": "ANEXO 3", "linhas": [...],
     "markdown": "..."}
"""
from datetime import date, datetime, time

FORMATO = "apoema-json-converter-v1"


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


def render_markdown_table(linhas, cabecalhos=None) -> str:
    """Render rows (list of lists) as a GitHub-style markdown table."""
    rows = list(linhas)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    if cabecalhos:
        header = [_markdown_cell(c) for c in cabecalhos]
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
    documento,
    tipo_documento,
    informativo,
    quadrienio=None,
    sha256=None,
    ferramenta="docling",
) -> dict:
    """Convert a DoclingDocument export dict into the enriched schema."""
    blocos = []
    for kind, idx in _body_order_items(docling_dict):
        if kind not in ("texts", "tables"):
            continue  # pictures/furniture: no text value for the pipeline
        item = docling_dict.get(kind, [])[idx]
        pagina = _page_of(item)
        if kind == "texts":
            texto = _clean(item.get("text"))
            if not texto:
                continue
            bloco = {"id": len(blocos) + 1, "tipo": "texto"}
            if pagina:
                bloco["pagina"] = pagina
            bloco["texto"] = texto
            blocos.append(bloco)
            continue

        # table
        data = item.get("data", {}) or {}
        grid = data.get("grid") or []
        # Headers = leading rows flagged column_header by the table model
        cabecalhos = []
        linhas = []
        for row in grid:
            cells = [_cell_text(c) for c in row]
            if all(
                isinstance(c, dict) and c.get("column_header") for c in row if c is not None
            ) and not cabecalhos and len(row) > 0 and all(c is not None for c in row):
                cabecalhos = cells
            else:
                linhas.append(cells)
        # drop spacer rows (empty everywhere)
        linhas = [r for r in linhas if any(c for c in r)]
        if not linhas and not cabecalhos:
            continue
        bloco = {"id": len(blocos) + 1, "tipo": "tabela"}
        if pagina:
            bloco["pagina"] = pagina
        if cabecalhos:
            bloco["cabecalhos"] = cabecalhos
        bloco["linhas"] = linhas
        bloco["markdown"] = render_markdown_table(linhas, cabecalhos or None)
        blocos.append(bloco)

    origem = {"formato_arquivo": "pdf"}
    if sha256:
        origem["sha256"] = sha256
    return _wrap(blocos, origem, documento, tipo_documento, informativo, quadrienio, ferramenta)


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


def serialize_xlsx(path, *, documento, tipo_documento, informativo, quadrienio=None,
                   sha256=None, ferramenta="openpyxl") -> dict:
    """Convert an XLSX workbook into planilha blocks (one per sheet)."""
    from openpyxl import load_workbook

    blocos = []
    abas = []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            abas.append(ws.title)
            linhas = []
            for row in ws.iter_rows(values_only=True):
                values = [_xlsx_value(v) for v in row]
                # trim trailing empty cells, drop fully-empty rows
                while values and values[-1] in ("", None):
                    values.pop()
                if any(v not in ("", None) for v in values):
                    linhas.append(["" if v is None else v for v in values])
            if not linhas:
                continue
            blocos.append(
                {
                    "id": len(blocos) + 1,
                    "tipo": "planilha",
                    "aba": ws.title,
                    "linhas": linhas,
                    "markdown": render_markdown_table(linhas),
                }
            )
    finally:
        wb.close()

    origem = {"formato_arquivo": "xlsx", "abas": abas}
    if sha256:
        origem["sha256"] = sha256
    return _wrap(blocos, origem, documento, tipo_documento, informativo, quadrienio, ferramenta)


# --------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------
def _wrap(blocos, origem, documento, tipo_documento, informativo, quadrienio, ferramenta) -> dict:
    from datetime import datetime, timezone

    return {
        "formato": FORMATO,
        "tipo_documento": tipo_documento,
        "documento": documento,
        "informativo": informativo,
        "quadrienio": quadrienio,
        "origem": origem,
        "conversao": {
            "ferramenta": ferramenta,
            "realizada_em": datetime.now(timezone.utc).isoformat(),
        },
        "blocos": blocos,
    }
