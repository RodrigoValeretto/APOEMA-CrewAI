"""
Tests for the zombie analysis cleanup (zombie_kill module + API endpoints).

Zombies are analyses stuck in 'processing'/'queued' whose worker died/stalled;
they block the FIFO gate forever. The cleanup marks them 'failed' and purges
the RabbitMQ queues so orphaned messages stop looping (the resurrection trap).
"""


def test_kill_zombie_analysis_marks_failed(monkeypatch):
    """A 'processing' analysis gets marked failed and queues get purged."""
    from zombie_kill import kill_zombie_analysis

    killed = {"id": 3, "type": "png_csv", "status": "processing"}
    purged = []

    monkeypatch.setattr(
        "zombie_kill.database.kill_zombie_analysis",
        lambda analysis_id: killed,
    )
    monkeypatch.setattr(
        "zombie_kill.purge_analysis_queues",
        lambda: 1,
    )

    result = kill_zombie_analysis(3)
    assert result == {
        "killed": True,
        "analysis_id": 3,
        "purged_messages": 1,
    }


def test_kill_zombie_analysis_not_zombie(monkeypatch):
    """A completed analysis is not a zombie: no purge, killed=False."""
    from zombie_kill import kill_zombie_analysis

    monkeypatch.setattr(
        "zombie_kill.database.kill_zombie_analysis",
        lambda analysis_id: None,
    )

    result = kill_zombie_analysis(3)
    assert result == {
        "killed": False,
        "analysis_id": 3,
        "purged_messages": 0,
    }


def test_cleanup_zombies_kills_only_stale(monkeypatch):
    """cleanup_zombies marks each stale analysis failed and purges once."""
    from zombie_kill import cleanup_zombies

    stale = [
        {"id": 3, "type": "png_csv", "status": "processing"},
        {"id": 4, "type": "basic", "status": "queued"},
    ]
    killed = []

    monkeypatch.setattr(
        "zombie_kill.database.get_stale_processing_analyses",
        lambda seconds: stale,
    )

    def _fake_kill(analysis_id):
        killed.append(analysis_id)
        return {"id": analysis_id, "status": "failed"}

    monkeypatch.setattr("zombie_kill.database.kill_zombie_analysis", _fake_kill)
    monkeypatch.setattr("zombie_kill.purge_analysis_queues", lambda: 2)

    result = cleanup_zombies(older_than_seconds=1800)
    assert result["killed"] == [3, 4]
    assert result["purged_messages"] == 2
    assert result["checked"] == 2


def test_cleanup_zombies_no_purge_when_nothing_killed(monkeypatch):
    """No stale analyses → no queue purge."""
    from zombie_kill import cleanup_zombies

    monkeypatch.setattr(
        "zombie_kill.database.get_stale_processing_analyses",
        lambda seconds: [],
    )

    result = cleanup_zombies(older_than_seconds=1800)
    assert result == {"killed": [], "purged_messages": 0, "checked": 0}


def test_run_watchdog_once_never_raises(monkeypatch):
    """The watchdog loop must survive a DB failure (never raise)."""
    from zombie_kill import run_watchdog_once

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "zombie_kill.database.get_stale_processing_analyses",
        _boom,
    )

    result = run_watchdog_once(older_than_seconds=1800)
    assert result["killed"] == []
    assert "error" in result
