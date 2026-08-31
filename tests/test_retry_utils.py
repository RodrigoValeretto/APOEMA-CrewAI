"""
Tests for retry_utils: transient-error detection, backoff retry, and run
checkpoints (resume support). No LLM calls — pure logic tests.
"""

import time

import pytest


# ─── Transient error detection ─────────────────────────────────────


class FakeAPIError(Exception):
    """Mimics google.genai.errors.APIError shape (module + .code)."""

    code: int | None = None


FakeAPIError.__module__ = "google.genai.errors"


def test_transient_detects_genai_5xx_and_429():
    from retry_utils import is_transient_error

    for code in (429, 500, 502, 503, 504):
        err = FakeAPIError(f"err {code}")
        err.code = code
        assert is_transient_error(err) is True

    err = FakeAPIError("400 bad request")
    err.code = 400
    assert is_transient_error(err) is False


def test_transient_detects_genai_without_code():
    from retry_utils import is_transient_error

    assert is_transient_error(FakeAPIError("transport error")) is True


def test_transient_detects_httpx_and_timeouts():
    from retry_utils import is_transient_error

    class FakeConnectError(Exception):
        pass

    FakeConnectError.__module__ = "httpx"
    assert is_transient_error(FakeConnectError("conn")) is True
    assert is_transient_error(TimeoutError("slow")) is True


def test_transient_rejects_non_transient():
    from retry_utils import is_transient_error

    assert is_transient_error(ValueError("bad input")) is False
    assert is_transient_error(KeyError("nope")) is False
    err = FakeAPIError("400 bad request")
    err.code = 400
    assert is_transient_error(err) is False, "400 is not transient"


def test_daily_quota_429_is_not_transient():
    """Daily-quota exhaustion (PerDay quotaId) must fail fast, not retry."""
    from retry_utils import is_transient_error

    msg = (
        "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        "limit: 20, model: gemini-2.5-flash. quotaId: "
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    )
    err = FakeAPIError(msg)
    err.code = 429
    assert is_transient_error(err) is False, "daily quota 429 must not be retried"

    # The same 429 without the PerDay marker (per-minute rate limit) IS transient
    err2 = FakeAPIError("429 RESOURCE_EXHAUSTED. Please retry in 10s.")
    err2.code = 429
    assert is_transient_error(err2) is True, "per-minute 429 should still retry"


def test_daily_quota_via_fallback_message():
    """Non-genai errors carrying the PerDay marker in their text also fail fast."""
    from retry_utils import is_transient_error

    class GenericErr(Exception):
        pass

    msg = (
        "429 RESOURCE_EXHAUSTED - GenerateRequestsPerDayPerProjectPerModel "
        "free_tier_requests limit 20"
    )
    assert is_transient_error(GenericErr(msg)) is False


# ─── Retry with backoff ─────────────────────────────────────────────


def test_retry_succeeds_after_transient_failures():
    from retry_utils import retry_with_backoff

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            err = FakeAPIError("high demand")
            err.code = 503
            raise err
        return "ok"

    assert retry_with_backoff(flaky, attempts=5, base_delay=0.01) == "ok"
    assert calls["n"] == 3


def test_retry_exhausts_and_raises():
    from retry_utils import retry_with_backoff

    def always_fails():
        err = FakeAPIError("always busy")
        err.code = 503
        raise err

    start = time.monotonic()
    with pytest.raises(FakeAPIError):
        retry_with_backoff(always_fails, attempts=3, base_delay=0.01)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.01, "backoff should have slept between attempts"


def test_retry_does_not_retry_non_transient():
    from retry_utils import retry_with_backoff

    calls = {"n": 0}

    def hard_fail():
        calls["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        retry_with_backoff(hard_fail, attempts=5, base_delay=0.01)
    assert calls["n"] == 1, "non-transient errors must not be retried"


# ─── Checkpoint helpers ─────────────────────────────────────────────


def test_checkpoint_roundtrip(tmp_path, monkeypatch):
    import retry_utils

    monkeypatch.setattr(retry_utils, "CHECKPOINT_DIR", tmp_path)
    retry_utils.save_task_checkpoint("runA", "task_1", "output 1", "assessment.json")
    retry_utils.save_task_checkpoint("runA", "task_2", "output 2", "assessment.json")

    ckpt = retry_utils.load_checkpoint("runA")
    assert retry_utils.completed_tasks(ckpt) == {"task_1", "task_2"}
    assert retry_utils.get_task_output(ckpt, "task_1") == "output 1"
    assert retry_utils.get_task_output(ckpt, "missing") == ""

    # Absent checkpoint → empty
    assert retry_utils.load_checkpoint("nope") == {}


def test_checkpoint_input_mismatch(tmp_path, monkeypatch):
    import retry_utils

    monkeypatch.setattr(retry_utils, "CHECKPOINT_DIR", tmp_path)
    assessment = tmp_path / "a.json"
    assessment.write_text("data")
    retry_utils.save_task_checkpoint("runB", "task_1", "out", str(assessment))

    ckpt = retry_utils.load_checkpoint("runB")
    assert retry_utils.checkpoint_matches_inputs(ckpt, str(assessment)) is True

    # Same path but different content → different mtime/size → mismatch
    time.sleep(0.01)
    assessment.write_text("different data longer")
    assert retry_utils.checkpoint_matches_inputs(ckpt, str(assessment)) is False

    # Different file entirely → mismatch
    other = tmp_path / "b.json"
    other.write_text("x")
    assert retry_utils.checkpoint_matches_inputs(ckpt, str(other)) is False
