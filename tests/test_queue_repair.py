"""Tests for the queue-repair module (orphaned 'pending' analyses).

A queue purge deletes RabbitMQ messages while their rows stay 'pending', so
the FIFO gate deadlocks (pending > 0, processing == 0 forever). These tests
cover rebuilding inputs from file mappings, the repair pass, and the
deadlock predicate.
"""
from api.exceptions import InvalidAnalysisInput


def test_rebuild_analysis_inputs_from_mappings(monkeypatch):
    """Assessment + png + csv + attachment mappings rebuild into the right shape."""
    import api.queue_repair as qr

    mappings = [
        {"file_type": "assessment", "file_path": "/app/uploads/conv/doc.json"},
        {"file_type": "png", "file_path": "/app/uploads/chart.png"},
        {"file_type": "csv", "file_path": "/app/uploads/chart.csv"},
        {"file_type": "attachment", "file_path": "/app/uploads/extra1.json"},
        {"file_type": "attachment", "file_path": "/app/uploads/extra2.json"},
    ]
    monkeypatch.setattr(qr.database, "get_analysis_files", lambda aid: mappings)
    monkeypatch.setattr(qr.os.path, "exists", lambda p: True)

    result = qr.rebuild_analysis_inputs(42)
    assert result["assessment_file"] == "/app/uploads/conv/doc.json"
    assert result["png_file"] == "/app/uploads/chart.png"
    assert result["csv_file"] == "/app/uploads/chart.csv"
    assert result["pdf_file"] == ""
    assert result["knowledge_files"] == [
        "/app/uploads/extra1.json",
        "/app/uploads/extra2.json",
    ]


def test_rebuild_analysis_inputs_requires_assessment(monkeypatch):
    """No assessment mapping raises InvalidAnalysisInput."""
    import api.queue_repair as qr

    monkeypatch.setattr(
        qr.database,
        "get_analysis_files",
        lambda aid: [{"file_type": "png", "file_path": "/x.png"}],
    )
    monkeypatch.setattr(qr.os.path, "exists", lambda p: True)

    try:
        qr.rebuild_analysis_inputs(42)
        assert False, "expected InvalidAnalysisInput"
    except InvalidAnalysisInput:
        pass


def test_repair_orphaned_pending_reenqueues_in_fifo_order(monkeypatch):
    """Every pending analysis is re-enqueued, and skips carry a reason."""
    import api.queue_repair as qr
    import tasks

    sent = []

    class _Sender:
        @staticmethod
        def send(**kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(
        tasks,
        "enqueue_analysis_for_sequential_processing",
        _Sender(),
    )
    pending = [
        {"id": 1367, "model": "ollama", "important_programs": None},
        {"id": 1368, "model": "ollama", "important_programs": None},
    ]
    monkeypatch.setattr(qr.database, "get_pending_analyses", lambda limit: pending)

    def _rebuild(aid):
        if aid == 1367:
            return {
                "assessment_file": "/a.json",
                "pdf_file": "",
                "png_file": "/p.png",
                "csv_file": "/c.csv",
                "knowledge_files": [],
            }
        raise InvalidAnalysisInput(f"no mapping for {aid}")

    monkeypatch.setattr(qr, "rebuild_analysis_inputs", _rebuild)

    result = qr.repair_orphaned_pending()
    assert result["checked"] == 2
    assert result["reenqueued"] == 1
    assert [s["analysis_id"] for s in sent] == [1367]
    assert result["skipped"][0]["id"] == 1368


def test_gate_is_deadlocked(monkeypatch):
    """Deadlock = pending > 0 with processing == 0."""
    import api.queue_repair as qr

    monkeypatch.setattr(qr.database, "count_processing_analyses", lambda: 0)
    monkeypatch.setattr(qr.database, "count_pending_analyses", lambda: 5)
    assert qr.gate_is_deadlocked() is True

    monkeypatch.setattr(qr.database, "count_processing_analyses", lambda: 1)
    assert qr.gate_is_deadlocked() is False


def test_run_orphan_repair_once_noop_when_healthy(monkeypatch):
    """No repair (and no enqueue) when the gate is not deadlocked."""
    import api.queue_repair as qr

    monkeypatch.setattr(qr, "gate_is_deadlocked", lambda: False)
    called = {"n": 0}

    def _boom(*a, **kw):
        called["n"] += 1

    monkeypatch.setattr(qr, "repair_orphaned_pending", _boom)

    result = qr.run_orphan_repair_once()
    assert result["deadlocked"] is False
    assert result["reenqueued"] == 0
    assert called["n"] == 0


def test_run_orphan_repair_once_never_raises(monkeypatch):
    """A DB failure during the predicate returns an error summary, never raises."""
    import api.queue_repair as qr

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(qr.database, "count_processing_analyses", _boom)

    result = qr.run_orphan_repair_once()
    assert "error" in result


def test_cancel_pending_marks_cancelled_and_purges(monkeypatch):
    """cancel_pending purges the queues and cancels every pending analysis."""
    import api.queue_repair as qr

    purged = {"n": 0}

    def _fake_purge():
        purged["n"] += 999
        return 999

    monkeypatch.setattr("zombie_kill.purge_analysis_queues", _fake_purge)
    monkeypatch.setattr(qr.database, "cancel_pending_analyses", lambda: 1218)

    result = qr.cancel_pending()
    assert result == {"cancelled": 1218, "purged_messages": 999}


def test_cancel_pending_skips_purge_when_disabled(monkeypatch):
    """purge=False leaves the queues untouched."""
    import api.queue_repair as qr

    called = {"n": 0}

    def _fake_purge():
        called["n"] += 1
        return 0

    monkeypatch.setattr("zombie_kill.purge_analysis_queues", _fake_purge)
    monkeypatch.setattr(qr.database, "cancel_pending_analyses", lambda: 3)

    result = qr.cancel_pending(purge=False)
    assert result == {"cancelled": 3, "purged_messages": 0}
    assert called["n"] == 0
