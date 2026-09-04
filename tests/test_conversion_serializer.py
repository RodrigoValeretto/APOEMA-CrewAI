"""Unit tests for the enriched document-conversion schema (conversion.serialize).

The PDF serializer is exercised against a synthetic DoclingDocument export dict
(mirroring docling 2.x: grid cells are dicts with .text/.column_header), so no
docling/torch install is required. XLSX tests run only when openpyxl is present.
"""
import json

import pytest

from conversion.serialize import (
    FORMATO,
    render_markdown_table,
    serialize_pdf_docling,
    serialize_xlsx,
)


def _cell(text, *, column_header=False, col_span=1):
    return {
        "bbox": {"l": 0.0, "t": 0.0, "r": 10.0, "b": 10.0, "coord_origin": "TOPLEFT"},
        "row_span": 1,
        "col_span": col_span,
        "start_row_offset_idx": 0,
        "end_row_offset_idx": 1,
        "start_col_offset_idx": 0,
        "end_col_offset_idx": col_span,
        "text": text,
        "column_header": column_header,
        "row_header": False,
        "row_section": False,
        "fillable": False,
    }


def _table(grid_rows, *, page=3):
    """Build a docling table export item from lists of cell specs."""
    grid = []
    for row in grid_rows:
        grid.append([_cell(text, column_header=hdr) for text, hdr in row])
    return {
        "self_ref": "#/tables/0",
        "prov": [{"page_no": page, "bbox": {"l": 0, "t": 0, "r": 100, "b": 100}}],
        "data": {
            "num_rows": len(grid),
            "num_cols": max(len(r) for r in grid),
            "orientation": "portrait",
            "grid": grid,
        },
    }


def _docling_export():
    """Minimal DoclingDocument export dict: text, table, picture, empty text."""
    return {
        "schema_name": "DoclingDocument",
        "version": "1.9.0",
        "body": {
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/tables/0"},
                {"$ref": "#/pictures/0"},
                {"$ref": "#/texts/1"},
            ]
        },
        "texts": [
            {"text": "Fichas de Avaliação Acadêmico e Profissional", "prov": [{"page_no": 1}]},
            {"text": "   \n  ", "prov": [{"page_no": 2}]},  # whitespace-only: skipped
        ],
        "pictures": [{"prov": [{"page_no": 1}]}],
        "tables": [
            _table(
                [
                    [("Quesitos/Itens", True), ("Peso", True), ("Peso", True)],
                    [("1 – PROGRAMA", False), ("Acadêmico", False), ("Profissional", False)],
                    [("1.1. Identidade e condições", False), ("50%", False), ("50%", False)],
                ],
                page=3,
            )
        ],
    }


class TestSerializePdfDocling:
    def test_blocks_in_reading_order(self):
        result = serialize_pdf_docling(
            _docling_export(),
            documento="COMPUTACAO_FICHA_2025_2028.pdf",
            tipo_documento="ficha",
            informativo="ciencia_da_computacao",
            quadrienio="2025-2028",
            sha256="abc123",
        )
        assert result["formato"] == FORMATO
        assert result["tipo_documento"] == "ficha"
        assert result["documento"] == "COMPUTACAO_FICHA_2025_2028.pdf"
        assert result["informativo"] == "ciencia_da_computacao"
        assert result["quadrienio"] == "2025-2028"
        assert result["origem"]["formato_arquivo"] == "pdf"
        assert result["origem"]["sha256"] == "abc123"

        # picture + whitespace-only text must be dropped: texto(1) tabela(3)
        blocos = result["blocos"]
        assert [b["tipo"] for b in blocos] == ["texto", "tabela"]
        assert blocos[0]["pagina"] == 1
        assert blocos[0]["texto"] == "Fichas de Avaliação Acadêmico e Profissional"

    def test_table_headers_rows_markdown(self):
        result = serialize_pdf_docling(
            _docling_export(),
            documento="x.pdf",
            tipo_documento="ficha",
            informativo="cc",
        )
        tabela = result["blocos"][1]
        assert tabela["tipo"] == "tabela"
        assert tabela["pagina"] == 3
        assert tabela["cabecalhos"] == ["Quesitos/Itens", "Peso", "Peso"]
        assert tabela["linhas"][0] == ["1 – PROGRAMA", "Acadêmico", "Profissional"]
        assert tabela["linhas"][1][1] == "50%"
        assert "| Quesitos/Itens | Peso | Peso |" in tabela["markdown"]
        assert "| --- | --- | --- |" in tabela["markdown"]
        assert "| 1.1. Identidade e condições | 50% | 50% |" in tabela["markdown"]

    def test_empty_export_produces_no_blocks(self):
        result = serialize_pdf_docling(
            {"body": {"children": []}, "texts": [], "tables": [], "pictures": []},
            documento="x.pdf",
            tipo_documento="anexo",
            informativo="adm",
        )
        assert result["blocos"] == []

    def test_json_roundtrip(self):
        result = serialize_pdf_docling(
            _docling_export(),
            documento="x.pdf",
            tipo_documento="ficha",
            informativo="cc",
        )
        # must be JSON-serializable (datetime-free) for the converter job
        json.dumps(result, ensure_ascii=False)
        assert isinstance(result["blocos"][1]["linhas"][1][1], str)


class TestRenderMarkdown:
    def test_escapes_pipes_and_newlines(self):
        md = render_markdown_table([["a|b\nc", "x"]])
        assert "| a\\|b c | x |" in md

    def test_headerless(self):
        md = render_markdown_table([["a", "b"], ["1", "2"]])
        assert md.count("|") >= 2
        assert "| ---" not in md  # no separator without headers


class TestSerializeXlsx:
    def test_planilha_blocks(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ANEXO 3"
        ws.append(["Indicador", "2024", "2025"])
        ws.append(["Artigos A1", 12, 15.0])
        ws.append([None, None, None])  # spacer row: dropped
        ws2 = wb.create_sheet("ANEXO 4")
        ws2.append(["Programa", "Conceito"])
        ws2.append(["CC", "5"])
        path = tmp_path / "anexo.xlsx"
        wb.save(path)
        wb.close()

        result = serialize_xlsx(
            str(path),
            documento="anexo.xlsx",
            tipo_documento="anexo",
            informativo="ciencia_da_computacao",
        )
        assert result["origem"]["formato_arquivo"] == "xlsx"
        assert result["origem"]["abas"] == ["ANEXO 3", "ANEXO 4"]
        blocos = result["blocos"]
        assert [b["tipo"] for b in blocos] == ["planilha", "planilha"]
        assert blocos[0]["aba"] == "ANEXO 3"
        # header labels typed as text stay str; numeric cells keep their type
        assert blocos[0]["linhas"] == [["Indicador", "2024", "2025"], ["Artigos A1", 12, 15]]
        assert blocos[1]["linhas"] == [["Programa", "Conceito"], ["CC", "5"]]
        assert "| Artigos A1 | 12 | 15 |" in blocos[0]["markdown"]
