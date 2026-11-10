"""Tests for the APOEMA report ingestion (data access + endpoint)."""
import json

import pytest
from fastapi.testclient import TestClient

from api import report_ingestion as ri
from api.fichas_catalog import area_code_from_name, ficha_key


class TestReportIdValidation:
    def test_valid_md5(self):
        assert ri.validate_report_id("b4c319228b363dc55611ca3e78cb1f8a") is True

    def test_rejects_non_hex(self):
        assert ri.validate_report_id("b4c319;rm -rf") is False
        assert ri.validate_report_id("../../etc") is False
        assert ri.validate_report_id("") is False

    def test_chart_id_validation(self):
        assert ri.validate_chart_id("00-doc-origem.png") is True
        assert ri.validate_chart_id("../../x.png") is False


class TestUrls:
    def test_png_url_keeps_literal_plus(self):
        url = ri.chart_png_url("abc123", "00-doc.png")
        assert url == "https://sistemas.prpg.usp.br/chart/abc123+00-doc.png"

    def test_csv_url_encodes_filename(self):
        png = ri.chart_png_url("abc123", "00-doc.png")
        url = ri.chart_csv_url(png)
        assert url.startswith(
            "https://sistemas.prpg.usp.br:9396/api/v1/chartcsv?filename=https%3A%2F%2F"
        )


class TestReportAreaName:
    def test_extracts_area_from_progs(self):
        info = {"progs": "SAA/SI-A-5-PAS:2021,2022@Zootecnia - Recursos Pesqueiros"}
        assert ri.report_area_name(info) == "Zootecnia - Recursos Pesqueiros"

    def test_no_at_returns_empty(self):
        assert ri.report_area_name({"progs": "nothing here"}) == ""
        assert ri.report_area_name({}) == ""


class TestChartCsvText:
    def test_serializes_with_human_headers(self):
        payload = {
            "status": "ok",
            "headers": [
                {"text": "", "value": "f0"},
                {"text": "Sigla", "value": "f1"},
                {"text": "Ano", "value": "f3"},
            ],
            "data": [
                {"f0": 303.0, "f1": "UFBA-A-5-Z", "f3": 2008.0},
                {"f0": 304.0, "f1": "UFBA-A-5-Z", "f3": 2004.0},
            ],
        }
        text = ri.chart_csv_text(payload)
        lines = text.strip().splitlines()
        assert lines[0] == "f0,Sigla,Ano"  # empty text falls back to the raw key
        assert len(lines) == 3  # header + 2 rows
        assert "UFBA-A-5-Z" in text

    def test_empty_data_returns_empty_string(self):
        assert ri.chart_csv_text({"data": []}) == ""
        assert ri.chart_csv_text({}) == ""


class TestAreaReverseLookup:
    def test_hyphen_variant_resolves(self):
        assert area_code_from_name("Zootecnia - Recursos Pesqueiros") == "ZOOTECNIA"
        assert area_code_from_name("Zootecnia / Recursos Pesqueiros") == "ZOOTECNIA"
        assert ficha_key("ZOOTECNIA") == "zootecnia"

    def test_unknown_name_returns_none(self):
        assert area_code_from_name("Área Inexistente") is None


class TestIngestEndpoint:
    """Endpoint behavior with the external APOEMA client and DB mocked out."""

    def _stub_ingest(self, monkeypatch):
        from api import api as api_module

        # Chart list: one with file, one without.
        charts = [
            {"url_n": "00-doc.png", "id": "00-doc.png", "hasfile": True},
            {"url_n": "32-start-dout.png", "id": "32-start-dout.png", "hasfile": False},
        ]

        captured = {}

        monkeypatch.setattr(
            api_module.report_ingestion,
            "fetch_report_info",
            lambda report_id: {"progs": "X:2021@Zootecnia - Recursos Pesqueiros"},
        )
        monkeypatch.setattr(
            api_module.report_ingestion,
            "fetch_charts",
            lambda report_id: charts,
        )
        monkeypatch.setattr(
            api_module.report_ingestion,
            "fetch_chart_csv",
            lambda png_url: {
                "headers": [{"text": "Sigla", "value": "f1"}],
                "data": [{"f1": "UFBA-A-5-Z"}],
            },
        )

        # DB: an informativo exists and has a converted ficha.
        monkeypatch.setattr(
            api_module.database,
            "get_informativo_by_slug",
            lambda slug: {"id": 7, "nome": "Zootecnia", "slug": slug},
        )
        monkeypatch.setattr(
            api_module.database,
            "get_report_png_urls",
            lambda ref: set(),
        )
        monkeypatch.setattr(
            api_module,
            "_resolve_informativo_inputs",
            lambda informativo_id: ("/app/uploads/ficha.json", 10, [], []),
        )

        async def _fake_download(url, file_type):
            return 101, f"/app/uploads/{file_type.value}_chart.png"

        monkeypatch.setattr(
            api_module.file_manager,
            "download_file_from_url",
            _fake_download,
        )
        monkeypatch.setattr(
            api_module.file_manager,
            "save_text_file",
            lambda text, file_type, name, url=None: (
                102,
                f"/app/uploads/{name}.csv",
            ),
        )

        analysis_ids = iter([1000])

        monkeypatch.setattr(
            api_module.database,
            "create_analysis",
            lambda **kw: next(analysis_ids),
        )
        monkeypatch.setattr(
            api_module.database,
            "create_analysis_file_mapping",
            lambda **kw: None,
        )
        monkeypatch.setattr(
            api_module.enqueue_analysis_for_sequential_processing,
            "send",
            lambda **kw: captured.update(kw),
        )

        return api_module, captured

    def test_ingest_creates_analysis_for_chart_with_file(self, monkeypatch):
        api_module, captured = self._stub_ingest(monkeypatch)
        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/ingest",
            json={"report_id": "b4c319228b363dc55611ca3e78cb1f8a"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created"] == 1
        assert body["skipped"] == 1  # the hasfile=False chart
        assert body["total_charts"] == 2
        assert body["report_reference"] == "b4c319228b363dc55611ca3e78cb1f8a"
        assert body["informativo_key"] == "zootecnia"
        assert captured["png_file"] == "/app/uploads/png_chart.png"
        assert captured["assessment_file"] == "/app/uploads/ficha.json"

    def test_ingest_requires_resolvable_informativo(self, monkeypatch):
        from api import api as api_module

        monkeypatch.setattr(
            api_module.report_ingestion,
            "fetch_report_info",
            lambda report_id: {"progs": "X@Área Desconhecida"},
        )
        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/ingest",
            json={"report_id": "b4c319228b363dc55611ca3e78cb1f8a"},
        )
        assert resp.status_code == 400, resp.text

    def test_ingest_rejects_invalid_report_id(self, monkeypatch):
        from api import api as api_module

        client = TestClient(api_module.app)
        resp = client.post("/api/reports/ingest", json={"report_id": "not-a-md5!"})
        assert resp.status_code == 400, resp.text
