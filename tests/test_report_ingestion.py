"""Tests for the APOEMA report ingestion (data access + endpoint + batch)."""
import sys

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


class TestReportService:
    """The shared synchronous ingest (used by the single endpoint and the batch)."""

    def _stub(self, monkeypatch):
        import types

        from api import report_service as svc

        captured = {}

        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_report_info",
            lambda report_id: {"progs": "X:2021@Zootecnia - Recursos Pesqueiros"},
        )
        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_charts",
            lambda report_id: [
                {"url_n": "00-doc.png", "id": "00-doc.png", "hasfile": True},
                {"url_n": "32-start-dout.png", "id": "32-start-dout.png", "hasfile": False},
            ],
        )
        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_chart_csv",
            lambda png_url: {
                "headers": [{"text": "Sigla", "value": "f1"}],
                "data": [{"f1": "UFBA-A-5-Z"}],
            },
        )
        monkeypatch.setattr(
            svc.database,
            "get_informativo_by_slug",
            lambda slug: {"id": 7, "nome": "Zootecnia", "slug": slug},
        )
        monkeypatch.setattr(svc.database, "get_report_png_urls", lambda ref: set())
        monkeypatch.setattr(
            svc,
            "_resolve_informativo_inputs",
            lambda informativo_id: ("/app/uploads/ficha.json", 10, [], []),
        )
        monkeypatch.setattr(
            svc.file_manager,
            "download_file_from_url_sync",
            lambda url, file_type, timeout=30: (101, "/app/uploads/chart.png"),
        )
        monkeypatch.setattr(
            svc.file_manager,
            "save_text_file",
            lambda text, file_type, name, url=None: (102, f"/app/uploads/{name}.csv"),
        )

        analysis_ids = iter([1000, 1001])
        monkeypatch.setattr(svc.database, "create_analysis", lambda **kw: next(analysis_ids))
        monkeypatch.setattr(svc.database, "create_analysis_file_mapping", lambda **kw: None)

        # Stub the lazy `tasks` import inside ingest_report.
        fake_tasks = types.SimpleNamespace(
            enqueue_analysis_for_sequential_processing=types.SimpleNamespace(
                send=lambda **kw: captured.update(kw)
            )
        )
        monkeypatch.setitem(sys.modules, "tasks", fake_tasks)

        return svc, captured

    def test_ingest_creates_analysis_for_chart_with_file(self, monkeypatch):
        svc, captured = self._stub(monkeypatch)
        resp = svc.ingest_report("b4c319228b363dc55611ca3e78cb1f8a", "ollama")
        assert resp.created == 1
        assert resp.skipped == 1  # the hasfile=False chart
        assert resp.total_charts == 2
        assert resp.report_reference == "b4c319228b363dc55611ca3e78cb1f8a"
        assert resp.informativo_key == "zootecnia"
        assert captured["png_file"] == "/app/uploads/chart.png"
        assert captured["assessment_file"] == "/app/uploads/ficha.json"

    def test_ingest_requires_resolvable_informativo(self, monkeypatch):
        from api import report_service as svc
        from api.exceptions import InvalidAnalysisInput

        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_report_info",
            lambda report_id: {"progs": "X@Área Desconhecida"},
        )
        with pytest.raises(InvalidAnalysisInput):
            svc.ingest_report("b4c319228b363dc55611ca3e78cb1f8a", "ollama")

    def test_unreachable_chart_does_not_abort_report(self, monkeypatch):
        """A chart whose PNG download fails (VPN-blocked route) is marked
        'failed' and the ingest continues — it must not abort the whole report."""
        from api import report_service as svc
        from api.exceptions import URLFetchError

        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_report_info",
            lambda report_id: {"progs": "X:2021@Zootecnia - Recursos Pesqueiros"},
        )
        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_charts",
            lambda report_id: [
                {"url_n": "00-doc.png", "id": "00-doc.png", "hasfile": True}
            ],
        )
        monkeypatch.setattr(
            svc.report_ingestion,
            "fetch_chart_csv",
            lambda png_url: {
                "headers": [{"text": "Sigla", "value": "f1"}],
                "data": [{"f1": "UFBA-A-5-Z"}],
            },
        )
        monkeypatch.setattr(
            svc.database,
            "get_informativo_by_slug",
            lambda slug: {"id": 7, "nome": "Zootecnia", "slug": slug},
        )
        monkeypatch.setattr(svc.database, "get_report_png_urls", lambda ref: set())
        monkeypatch.setattr(
            svc,
            "_resolve_informativo_inputs",
            lambda informativo_id: ("/app/uploads/ficha.json", 10, [], []),
        )

        def _failing_download(url, file_type, timeout=30):
            raise URLFetchError(f"Request timeout when downloading from: {url}")

        monkeypatch.setattr(
            svc.file_manager, "download_file_from_url_sync", _failing_download
        )

        resp = svc.ingest_report("b4c319228b363dc55611ca3e78cb1f8a", "ollama")
        assert resp.created == 0
        assert resp.failed == 1
        assert resp.charts[0].status == "failed"


class TestIngestEndpoint:
    """Single-report endpoint: delegates to the shared service."""

    def test_single_endpoint_delegates_to_service(self, monkeypatch):
        from api import api as api_module
        from api.models import ReportIngestResponse

        captured = {}

        def _fake_ingest(report_id, model, important_programs=None):
            captured.update(
                {
                    "report_id": report_id,
                    "model": model,
                    "important_programs": important_programs,
                }
            )
            return ReportIngestResponse(
                report_id=report_id,
                report_reference=report_id,
                area="Zootecnia - Recursos Pesqueiros",
                informativo_key="zootecnia",
                total_charts=2,
                created=1,
                skipped=1,
                failed=0,
                charts=[],
            )

        monkeypatch.setattr(api_module.report_service, "ingest_report", _fake_ingest)

        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/ingest",
            json={"report_id": "b4c319228b363dc55611ca3e78cb1f8a"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created"] == 1
        assert captured["report_id"] == "b4c319228b363dc55611ca3e78cb1f8a"
        assert captured["model"] == "ollama"

    def test_single_endpoint_rejects_invalid_report_id(self, monkeypatch):
        from api import api as api_module
        from api.exceptions import InvalidAnalysisInput

        def _raise(report_id, model, important_programs=None):
            raise InvalidAnalysisInput(f"Invalid report id: {report_id!r}")

        monkeypatch.setattr(api_module.report_service, "ingest_report", _raise)

        client = TestClient(api_module.app)
        resp = client.post("/api/reports/ingest", json={"report_id": "not-a-md5!"})
        assert resp.status_code == 400, resp.text


class TestBatchEndpoint:
    """List-of-reports endpoint: enqueues one batch actor message."""

    def test_batch_enqueues_and_returns_202(self, monkeypatch):
        from api import api as api_module

        captured = {}

        monkeypatch.setattr(
            api_module.ingest_report_batch,
            "send",
            lambda **kw: captured.update(kw),
        )

        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/ingest-batch",
            json={
                "reports_list": [
                    "b4c319228b363dc55611ca3e78cb1f8a",
                    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                ],
                "model": "ollama",
            },
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["total"] == 2
        assert [i["report_id"] for i in body["items"]] == [
            "b4c319228b363dc55611ca3e78cb1f8a",
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        ]
        assert captured["reports"] == [
            "b4c319228b363dc55611ca3e78cb1f8a",
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        ]
        assert captured["model"] == "ollama"

    def test_batch_rejects_invalid_report_id(self, monkeypatch):
        from api import api as api_module

        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/ingest-batch",
            json={"reports_list": ["not-a-md5!"]},
        )
        assert resp.status_code == 400, resp.text

    def test_batch_requires_reports_list(self, monkeypatch):
        from api import api as api_module

        client = TestClient(api_module.app)
        resp = client.post("/api/reports/ingest-batch", json={})
        assert resp.status_code == 422, resp.text
