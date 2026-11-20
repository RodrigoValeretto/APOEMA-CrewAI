"""Tests for the deleted-row guard in the analysis run actor.

When a report is reprocessed, its analyses are deleted while their Dramatiq
messages are still in flight. The run actor must DROP such a message (not
requeue it forever, which would loop) instead of running a flow whose row no
longer exists.
"""
from api.exceptions import AnalysisNotFound


class TestRunActorDeletedRowGuard:
    def test_deleted_row_drops_message(self, monkeypatch):
        import tasks

        calls = {"claimed": False, "ran": False}

        def _raise_not_found(analysis_id):
            raise AnalysisNotFound(analysis_id)

        def _fake_claim(analysis_id):
            calls["claimed"] = True
            return True

        def _fake_run(**kwargs):
            calls["ran"] = True
            return {}

        monkeypatch.setattr(tasks, "get_analysis", _raise_not_found)
        monkeypatch.setattr(tasks, "claim_analysis_processing_slot", _fake_claim)
        monkeypatch.setattr(tasks, "run_apoema_flow", _fake_run)

        result = tasks.run_analysis_flow_with_tracking.fn(
            analysis_id=999,
            assessment_file="/app/input/cc_assessment_data.json",
            pdf_file=None,
            png_file=None,
            csv_file=None,
            output_prefix="analysis_999",
            model="ollama",
            important_programs=None,
            knowledge_files=None,
        )

        assert result["status"] == "dropped"
        # Neither the slot claim nor the flow ran for a deleted row.
        assert calls["claimed"] is False
        assert calls["ran"] is False

    def test_existing_row_proceeds_to_claim(self, monkeypatch):
        import tasks

        calls = {"claimed": False}

        def _fake_get(analysis_id):
            return {"id": analysis_id, "status": "pending"}

        def _fake_claim(analysis_id):
            calls["claimed"] = True
            return False  # slot busy -> requeue path, but claim WAS attempted

        monkeypatch.setattr(tasks, "get_analysis", _fake_get)
        monkeypatch.setattr(tasks, "claim_analysis_processing_slot", _fake_claim)
        monkeypatch.setattr(
            tasks, "_requeue_through_gate", lambda *a, **kw: {"status": "queued"}
        )

        result = tasks.run_analysis_flow_with_tracking.fn(
            analysis_id=5,
            assessment_file="/app/input/cc_assessment_data.json",
            pdf_file=None,
            png_file=None,
            csv_file=None,
            output_prefix="analysis_5",
            model="ollama",
            important_programs=None,
            knowledge_files=None,
        )

        # The guard passed (row exists), so the claim was attempted.
        assert calls["claimed"] is True
        assert result["status"] == "queued"
