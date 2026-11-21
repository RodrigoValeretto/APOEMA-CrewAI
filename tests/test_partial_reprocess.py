"""Tests for the partial reprocess feature.

``partial=true`` deletes only a report's NON-completed analyses (keeping
``completed``) and re-runs the idempotent ingest, so only the deleted charts
are recreated as ``pending``. ``partial=false`` deletes everything and
re-ingests. Both return a ``ReportIngestResponse``.
"""
from fastapi.testclient import TestClient

from api import api as api_module

REPORT_ID = "b4c319228b363dc55611ca3e78cb1f8a"


class TestDeleteAnalysesByReportKeepStatuses:
    def test_keep_statuses_adds_not_in_clause(self, monkeypatch):
        from api import database

        captured = {}

        class _Cursor:
            def __init__(self, row_factory=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                captured.setdefault("sql", []).append((sql, params))

            def fetchall(self):
                return [[11], [12]]

        class _Conn:
            def cursor(self, row_factory=None):
                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def commit(self):
                pass

        monkeypatch.setattr(database, "get_connection", lambda: _Conn())

        result = database.delete_analyses_by_report(
            "rel-x", keep_statuses=["completed"]
        )
        assert result == [11, 12]
        select_sql, select_params = captured["sql"][0]
        assert "status NOT IN" in select_sql
        assert select_params == ["rel-x", "completed"]

    def test_no_keep_statuses_deletes_all(self, monkeypatch):
        from api import database

        captured = {}

        class _Cursor:
            def __init__(self, row_factory=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                captured.setdefault("sql", []).append((sql, params))

            def fetchall(self):
                return []

        class _Conn:
            def cursor(self, row_factory=None):
                return _Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def commit(self):
                pass

        monkeypatch.setattr(database, "get_connection", lambda: _Conn())

        database.delete_analyses_by_report("rel-x")
        select_sql, select_params = captured["sql"][0]
        assert "status NOT IN" not in select_sql
        assert select_params == ["rel-x"]


class TestPartialReprocessService:
    def _analyses(self):
        return [
            {"id": 11, "status": "failed"},
            {"id": 12, "status": "pending"},
            {"id": 13, "status": "processing"},
            {"id": 14, "status": "completed"},
        ]

    def test_partial_keeps_completed_deletes_rest(self, monkeypatch):
        from api import report_service

        delete_args = {}
        ingest_args = {}

        class _FakePath:
            def exists(self):
                return False

        monkeypatch.setattr(
            report_service.report_ingestion, "validate_report_id", lambda rid: True
        )
        monkeypatch.setattr(
            report_service.database,
            "get_analyses_by_report",
            lambda ref: self._analyses(),
        )
        monkeypatch.setattr(
            report_service.database,
            "get_analysis_files",
            lambda aid: [],
        )

        def _fake_delete(ref, keep_statuses=None):
            delete_args["keep"] = keep_statuses
            return [11, 12, 13]

        def _fake_ingest(rid, model, important_programs):
            ingest_args["called"] = True
            return "ingested"

        monkeypatch.setattr(
            report_service.database, "delete_analyses_by_report", _fake_delete
        )
        monkeypatch.setattr(report_service, "checkpoint_path", lambda p: _FakePath())
        monkeypatch.setattr(report_service, "ingest_report", _fake_ingest)

        result = report_service.reprocess_report(REPORT_ID, "ollama", None, partial=True)

        assert result == "ingested"
        assert delete_args["keep"] == ["completed"]
        assert ingest_args["called"] is True

    def test_full_deletes_everything(self, monkeypatch):
        from api import report_service

        delete_args = {}

        class _FakePath:
            def exists(self):
                return False

        monkeypatch.setattr(
            report_service.report_ingestion, "validate_report_id", lambda rid: True
        )
        monkeypatch.setattr(
            report_service.database,
            "get_analyses_by_report",
            lambda ref: self._analyses(),
        )
        monkeypatch.setattr(
            report_service.database,
            "get_analysis_files",
            lambda aid: [],
        )

        def _fake_delete(ref, keep_statuses=None):
            delete_args["keep"] = keep_statuses
            return [11, 12, 13, 14]

        def _fake_ingest(rid, model, important_programs):
            return "ingested"

        monkeypatch.setattr(
            report_service.database, "delete_analyses_by_report", _fake_delete
        )
        monkeypatch.setattr(report_service, "checkpoint_path", lambda p: _FakePath())
        monkeypatch.setattr(report_service, "ingest_report", _fake_ingest)

        report_service.reprocess_report(REPORT_ID, "ollama", None, partial=False)

        assert delete_args["keep"] is None


class TestPartialReprocessEndpoint:
    def test_partial_passes_flag_to_service(self, monkeypatch):
        captured = {}

        monkeypatch.setattr(
            api_module.report_ingestion, "validate_report_id", lambda rid: True
        )

        def _fake(rid, model, important_programs, partial):
            captured["partial"] = partial
            return {
                "report_id": rid,
                "report_reference": rid,
                "total_charts": 0,
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "charts": [],
            }

        monkeypatch.setattr(api_module.report_service, "reprocess_report", _fake)

        client = TestClient(api_module.app)
        resp = client.post(
            f"/api/reports/{REPORT_ID}/reprocess",
            json={"model": "ollama", "partial": True},
        )
        assert resp.status_code == 200, resp.text
        assert captured["partial"] is True

    def test_full_uses_partial_false(self, monkeypatch):
        captured = {}

        monkeypatch.setattr(
            api_module.report_ingestion, "validate_report_id", lambda rid: True
        )

        def _fake(rid, model, important_programs, partial):
            captured["partial"] = partial
            return {"report_id": rid, "charts": []}

        monkeypatch.setattr(api_module.report_service, "reprocess_report", _fake)

        client = TestClient(api_module.app)
        resp = client.post(
            f"/api/reports/{REPORT_ID}/reprocess",
            json={"model": "ollama", "partial": False},
        )
        assert resp.status_code == 200, resp.text
        assert captured["partial"] is False


class TestPartialReprocessBatchActor:
    def test_batch_passes_partial_to_service(self, monkeypatch):
        import tasks

        calls = []

        class _Resp:
            created = 1
            skipped = 0
            failed = 0

        def _fake_reprocess(rid, model, important_programs, partial):
            calls.append(partial)
            return _Resp()

        monkeypatch.setattr(
            "api.report_service.reprocess_report", _fake_reprocess
        )

        result = tasks.reprocess_report_batch.fn(
            reports=[REPORT_ID], model="ollama", important_programs=None, partial=True
        )
        assert calls == [True]
        assert result["results"][REPORT_ID]["status"] == "ok"
