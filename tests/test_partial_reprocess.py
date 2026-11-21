"""Tests for the partial reprocess feature.

``partial=true`` re-enqueues only a report's FAILED analyses (keeping
completed/pending/processing intact), instead of the full delete + re-ingest.
Covers the service function, the endpoint routing, and the batch actor branch.
"""
from fastapi.testclient import TestClient

from api import api as api_module

REPORT_ID = "b4c319228b363dc55611ca3e78cb1f8a"


def _failed_analyses():
    return [
        {"id": 11, "status": "failed", "model": "ollama", "important_programs": None},
        {"id": 12, "status": "failed", "model": None, "important_programs": None},
        {"id": 13, "status": "completed", "model": "ollama", "important_programs": None},
        {"id": 14, "status": "pending", "model": "ollama", "important_programs": None},
    ]


class TestPartialReprocessService:
    def test_requeues_only_failed(self, monkeypatch):
        from api import report_service

        sent = []

        class _Sender:
            @staticmethod
            def send(**kwargs):
                sent.append(kwargs)

        def _rebuild(aid):
            return {
                "assessment_file": f"/app/a{aid}.json",
                "pdf_file": "",
                "png_file": f"/app/p{aid}.png",
                "csv_file": f"/app/c{aid}.csv",
                "knowledge_files": [],
            }

        monkeypatch.setattr(
            report_service.report_ingestion, "validate_report_id", lambda rid: True
        )
        monkeypatch.setattr(
            report_service.database,
            "get_analyses_by_report",
            lambda ref: _failed_analyses(),
        )
        monkeypatch.setattr(
            "tasks.enqueue_analysis_for_sequential_processing", _Sender()
        )
        monkeypatch.setattr(
            "api.queue_repair.rebuild_analysis_inputs", _rebuild
        )

        result = report_service.reprocess_report_partial(REPORT_ID, "ollama")

        assert result.total_failed == 2
        assert result.requeued == 2
        assert result.skipped == 0
        # Completed (13) and pending (14) are never touched.
        assert sorted(s["analysis_id"] for s in sent) == [11, 12]
        # The stored per-analysis model wins over the request fallback.
        assert sent[0]["model"] == "ollama"  # stored
        assert sent[1]["model"] == "ollama"  # fallback (stored was None)


class TestPartialReprocessEndpoint:
    def test_partial_routes_to_partial_service(self, monkeypatch):
        captured = {}

        monkeypatch.setattr(
            api_module.report_ingestion, "validate_report_id", lambda rid: True
        )

        def _fake_partial(rid, model):
            captured["rid"] = rid
            captured["model"] = model
            return {
                "report_id": rid,
                "total_failed": 2,
                "requeued": 2,
                "skipped": 0,
                "items": [],
            }

        monkeypatch.setattr(
            api_module.report_service, "reprocess_report_partial", _fake_partial
        )

        client = TestClient(api_module.app)
        resp = client.post(
            f"/api/reports/{REPORT_ID}/reprocess",
            json={"model": "ollama", "partial": True},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_failed"] == 2
        assert body["requeued"] == 2
        assert captured["rid"] == REPORT_ID

    def test_partial_false_uses_full_reprocess(self, monkeypatch):
        monkeypatch.setattr(
            api_module.report_ingestion, "validate_report_id", lambda rid: True
        )

        def _fake_full(rid, model, important_programs):
            return {
                "report_id": rid,
                "report_reference": rid,
                "total_charts": 0,
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "charts": [],
            }

        monkeypatch.setattr(api_module.report_service, "reprocess_report", _fake_full)
        called = {"partial": False}

        def _fake_partial(rid, model):
            called["partial"] = True
            return {}

        monkeypatch.setattr(
            api_module.report_service, "reprocess_report_partial", _fake_partial
        )

        client = TestClient(api_module.app)
        resp = client.post(
            f"/api/reports/{REPORT_ID}/reprocess",
            json={"model": "ollama", "partial": False},
        )
        assert resp.status_code == 200, resp.text
        assert called["partial"] is False


class TestPartialReprocessBatchActor:
    def test_batch_partial_calls_partial_service(self, monkeypatch):
        import tasks

        calls = []

        def _fake_partial(rid, model):
            calls.append(("partial", rid, model))
            from api.models import ReportPartialReprocessResponse

            return ReportPartialReprocessResponse(
                report_id=rid, total_failed=1, requeued=1, skipped=0, items=[]
            )

        monkeypatch.setattr(
            "api.report_service.reprocess_report_partial", _fake_partial
        )

        result = tasks.reprocess_report_batch.fn(
            reports=[REPORT_ID], model="ollama", important_programs=None, partial=True
        )
        assert calls == [("partial", REPORT_ID, "ollama")]
        assert result["results"][REPORT_ID]["status"] == "ok"
        assert result["results"][REPORT_ID]["requeued"] == 1
