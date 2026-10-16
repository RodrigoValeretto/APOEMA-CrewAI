"""Tests for the report-reference feature (group analyses into a report)."""
from fastapi.testclient import TestClient

from api.models import AnalysisRequest, ReportResponse, ReportAnalysisItem
from api.validators import validate_analysis_request


class TestReportReferenceRequest:
    def test_report_reference_default_none(self):
        request = AnalysisRequest.model_construct()
        assert request.report_reference is None

    def test_report_reference_accepted(self):
        request = AnalysisRequest.model_construct(
            assessment_file_id=1,
            model="ollama",
            report_reference="relatorio-2025-cc",
        )
        assert request.report_reference == "relatorio-2025-cc"

    def test_report_reference_is_optional_in_validation(self):
        # A request WITHOUT report_reference stays valid (feature is additive).
        is_valid, _ = validate_analysis_request(assessment_file_id=1)
        assert is_valid is True


class TestReportResponseModel:
    def test_empty_report(self):
        report = ReportResponse(report_reference="rel-x", total=0, analyses=[])
        assert report.report_reference == "rel-x"
        assert report.total == 0
        assert report.analyses == []

    def test_report_item_carries_image_path(self):
        item = ReportAnalysisItem(
            id=7,
            type="png_csv",
            status="completed",
            created_at="2026-10-06T12:00:00Z",
            png_path="/app/uploads/plot_7.png",
            csv_path="/app/uploads/plot_7.csv",
            results=[],
        )
        assert item.png_path == "/app/uploads/plot_7.png"
        assert item.assessment_path is None


class TestDatabaseQuery:
    def test_get_analyses_by_report_orders_by_id(self, monkeypatch):
        """The report lookup must return analyses in creation order."""
        from api import database

        rows = [
            {"id": 5, "type": "png_csv", "status": "completed"},
            {"id": 3, "type": "basic", "status": "completed"},
        ]
        captured = {}

        def _fake_execute(sql, params):
            captured["params"] = params
            return None

        class _Cursor:
            def __init__(self, row_factory=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                _fake_execute(sql, params)

            def fetchall(self):
                return rows

        class _Conn:
            def cursor(self, row_factory=None):
                return _Cursor(row_factory)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(database, "get_connection", lambda: _Conn())

        result = database.get_analyses_by_report("rel-x")
        assert [r["id"] for r in result] == [5, 3]
        assert captured["params"] == ("rel-x",)


class TestRetryPreservesReportReference:
    """Retrying a failed analysis must keep its report_reference in the
    response, matching what the create endpoint echoes."""

    def test_retry_response_carries_report_reference(self, monkeypatch):
        from datetime import datetime

        from api import api as api_module

        analysis_row = {
            "id": 9,
            "type": "basic",
            "status": "failed",
            "model": "ollama",
            "important_programs": None,
            "informativo_id": None,
            "report_reference": "relatorio-retry",
            "created_at": datetime(2026, 10, 14, 12, 0, 0),
        }

        # A real file on disk so the input-exists guard passes.
        assessment_path = __file__

        monkeypatch.setattr(
            api_module.database, "get_analysis", lambda analysis_id: analysis_row
        )
        monkeypatch.setattr(
            api_module.database,
            "get_analysis_files",
            lambda analysis_id: [{"file_type": "assessment", "file_path": assessment_path}],
        )
        monkeypatch.setattr(
            api_module.enqueue_analysis_for_sequential_processing,
            "send",
            lambda **kwargs: None,
        )

        # No lifespan context manager: keeps the zombie watchdog from starting.
        client = TestClient(api_module.app)
        resp = client.post("/api/analysis/9/retry")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["report_reference"] == "relatorio-retry"
        assert body["id"] == 9
