"""Tests for report reprocess + batch status features.

Covers:
- ``database.get_report_status_counts`` groups by status.
- ``database.delete_analyses_by_report`` returns the deleted ids and issues the
  DELETE for the right reference.
- ``report_service.reprocess_report`` deletes analyses + checkpoints + chart
  files, then re-ingests.
- The ``POST /api/reports/{id}/reprocess`` and ``POST /api/reports/status``
  endpoints (real routes, mocked DB).
"""
from datetime import datetime

from fastapi.testclient import TestClient

from api import api as api_module


class TestDatabaseStatusCounts:
    def test_counts_grouped_by_status(self, monkeypatch):
        from api import database

        rows = [
            {"status": "completed", "count": 3},
            {"status": "failed", "count": 1},
        ]

        class _Cursor:
            def __init__(self, row_factory=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                return None

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

        result = database.get_report_status_counts("rel-x")
        assert result == {"completed": 3, "failed": 1}


class TestDatabaseDeleteByReport:
    def test_delete_returns_ids(self, monkeypatch):
        from api import database

        ids = [11, 12, 13]
        captured = {}

        class _Cursor:
            def __init__(self, row_factory=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                captured.setdefault("sql", []).append((sql, params))
                return None

            def fetchall(self):
                return [[i] for i in ids]

        class _Conn:
            def cursor(self, row_factory=None):
                return _Cursor(row_factory)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def commit(self):
                captured["commit"] = True

        monkeypatch.setattr(database, "get_connection", lambda: _Conn())

        result = database.delete_analyses_by_report("rel-x")
        assert result == ids
        # First statement selects, second deletes.
        assert captured["sql"][1][0].strip().startswith("DELETE FROM analysis")
        assert captured["sql"][1][1] == ("rel-x",)


class TestReprocessService:
    def test_reprocess_deletes_then_reingests(self, monkeypatch, tmp_path):
        from api import report_service

        deleted_file_ids: list = []
        ingest_args: tuple = ()
        chart_file = tmp_path / "chart.png"
        chart_file.write_text("x")
        checkpoint = tmp_path / "analysis_11.json"
        checkpoint.write_text("{}")

        analyses = [{"id": 11}]
        files = [
            {"id": 1, "file_type": "png", "file_path": str(chart_file)},
            {"id": 2, "file_type": "csv", "file_path": "/tmp/never.csv"},
            {"id": 3, "file_type": "assessment", "file_path": "/shared.json"},
        ]

        monkeypatch.setattr(
            report_service.report_ingestion, "validate_report_id", lambda rid: True
        )
        monkeypatch.setattr(
            report_service.database, "get_analyses_by_report", lambda ref: analyses
        )
        monkeypatch.setattr(
            report_service.database, "get_analysis_files", lambda aid: files
        )
        monkeypatch.setattr(
            report_service.database,
            "delete_analyses_by_report",
            lambda ref: [a["id"] for a in analyses],
        )
        monkeypatch.setattr(
            report_service, "checkpoint_path", lambda prefix: tmp_path / f"{prefix}.json"
        )
        monkeypatch.setattr(
            report_service.file_manager,
            "delete_file",
            lambda fid: deleted_file_ids.append(fid),
        )

        def _fake_ingest(rid, model, important_programs):
            nonlocal ingest_args
            ingest_args = (rid, model, important_programs)
            return "ingested"

        monkeypatch.setattr(report_service, "ingest_report", _fake_ingest)

        result = report_service.reprocess_report("rel-x", "ollama", None)

        assert result == "ingested"
        assert ingest_args == ("rel-x", "ollama", None)
        # Only png/csv deleted, not the shared assessment.
        assert sorted(deleted_file_ids) == [1, 2]
        # Checkpoint for the deleted analysis removed.
        assert not checkpoint.exists()


class TestReprocessEndpoint:
    def test_reprocess_route(self, monkeypatch):
        monkeypatch.setattr(
            api_module.report_ingestion, "validate_report_id", lambda rid: True
        )
        monkeypatch.setattr(
            api_module.report_service,
            "reprocess_report",
            lambda rid, model, important_programs: {
                "report_id": rid,
                "report_reference": rid,
                "total_charts": 2,
                "created": 2,
                "skipped": 0,
                "failed": 0,
                "charts": [],
            },
        )
        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/b4c319228b363dc55611ca3e78cb1f8a/reprocess",
            json={"model": "ollama"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["report_id"] == "b4c319228b363dc55611ca3e78cb1f8a"
        assert body["created"] == 2

    def test_reprocess_rejects_bad_id(self, monkeypatch):
        from api.exceptions import InvalidAnalysisInput

        monkeypatch.setattr(
            api_module.report_ingestion,
            "validate_report_id",
            lambda rid: False,
        )
        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/not-a-hex-token/reprocess", json={"model": "ollama"}
        )
        assert resp.status_code == 400, resp.text


class TestStatusEndpoint:
    def test_status_batch(self, monkeypatch):
        counts_by_ref = {
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
                "completed": 4,
                "failed": 1,
                "pending": 0,
                "processing": 0,
            },
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": {
                "completed": 0,
                "failed": 0,
                "pending": 5,
                "processing": 0,
            },
        }
        monkeypatch.setattr(
            api_module.report_ingestion, "validate_report_id", lambda rid: True
        )
        monkeypatch.setattr(
            api_module.database,
            "get_report_status_counts",
            lambda ref: counts_by_ref[ref],
        )
        client = TestClient(api_module.app)
        resp = client.post(
            "/api/reports/status",
            json={
                "reports_list": [
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        items = {i["report_id"]: i for i in resp.json()["items"]}

        first = items["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
        assert first["total"] == 5
        assert first["completion_pct"] == 80.0
        assert first["needs_reprocess"] is True

        second = items["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]
        assert second["total"] == 5
        assert second["completion_pct"] == 0.0
        assert second["needs_reprocess"] is False
