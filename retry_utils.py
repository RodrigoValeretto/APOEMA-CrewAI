"""Transient-error retry with exponential backoff + run checkpoints.

Why this exists: the Gemini provider in CrewAI has no retry of its own, and the
agent-level retry loop retries immediately (no backoff) with a budget that is
shared across all tasks of an agent. A 503 under load therefore kills the whole
pipeline. This module provides:

  - retry_with_backoff(): re-invoke a callable on transient errors (HTTP
    429/5xx, connection errors, timeouts) with exponential backoff + jitter.
  - Checkpoint helpers: persist each completed task's output as JSON under
    output/.checkpoints/<prefix>.json so a crashed run can be resumed from the
    last completed task instead of re-running (and re-paying for) earlier ones.
"""
import json
import os
import random
import time
from pathlib import Path

# HTTP status codes treated as transient (safe to retry)
TRANSIENT_STATUS = {429, 500, 502, 503, 504}

# Where per-run task checkpoints live (resume data for crashed pipelines)
CHECKPOINT_DIR = Path("output/.checkpoints")


def _is_daily_quota_exhaustion(msg: str) -> bool:
    """True when the message describes a *daily* quota (not per-minute rate limit).

    Gemini's daily-quota errors carry a quotaId like
    'GenerateRequestsPerDayPerProjectPerModel-FreeTier' (and the metric
    '..._free_tier_requests'); per-minute limits use different quotaIds.
    Retrying a daily quota within the same day is futile — fail fast instead.
    """
    return (
        "RESOURCE_EXHAUSTED" in msg
        and ("PerDay" in msg or "free_tier_requests" in msg)
    )


def is_transient_error(e: BaseException) -> bool:
    """Return True when the error is a transient API/network failure worth retrying.

    A 429 from a *daily* quota (e.g. the Gemini free tier: 20 req/day) is NOT
    transient — retrying within the same day is futile and just burns
    time/requests. Only per-minute rate limits (429 without quota exhaustion)
    are worth retrying.
    """
    module = type(e).__module__
    msg = str(e)
    # google.genai.errors.APIError (Gemini provider) — has a .code HTTP status
    if module.startswith("google.genai") or "APIError" in type(e).__name__:
        code = getattr(e, "code", None)
        # Daily-quota exhaustion: RESOURCE_EXHAUSTED with a PerDay quotaId → fail fast
        if code in (429, "429") and _is_daily_quota_exhaustion(msg):
            return False
        if code is None:
            # GenAI errors without an HTTP code (transport-level) are transient
            return True
        try:
            return int(code) in TRANSIENT_STATUS
        except (TypeError, ValueError):
            return True
    # httpx network errors: ConnectError, TimeoutException, ReadError, ...
    if module.startswith("httpx"):
        return True
    # Generic timeouts
    if isinstance(e, TimeoutError):
        return True
    # Fallback: explicit status strings in the message (provider-agnostic)
    if "429" in msg or "503" in msg or "502" in msg or "504" in msg:
        if "429" in msg and _is_daily_quota_exhaustion(msg):
            return False
        return "quota" in msg.lower() or "demand" in msg.lower() or "unavailable" in msg.lower()
    return False


def retry_with_backoff(
    fn,
    attempts: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    label: str = "call",
):
    """Call fn(), retrying on transient errors with exponential backoff + jitter.

    Non-transient errors raise immediately (no wasted retries). Returns fn()'s
    result on success; raises the last error once attempts are exhausted.
    """
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - we inspect and re-raise below
            last_error = e
            if not is_transient_error(e):
                raise
            if attempt == attempts:
                break
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay) + random.uniform(0, 0.5)
            print(
                f"⚠️  {label} failed (attempt {attempt}/{attempts}): "
                f"{type(e).__name__}: {str(e)[:160]} — retrying in {delay:.0f}s"
            )
            time.sleep(delay)
    # last_error is always set here (attempts >= 1); keep the type checker honest
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"{label} failed with no error captured")


def _input_fingerprint(assessment_file: str, png_path=None, csv_path=None) -> dict:
    """Hash input files (path + size + mtime) so checkpoints are not reused with different inputs."""
    fingerprint = {}
    for key, path in (
        ("assessment", assessment_file),
        ("png", png_path),
        ("csv", csv_path),
    ):
        if not path or not os.path.exists(path):
            continue
        stat = os.stat(path)
        fingerprint[key] = {"path": os.path.basename(path), "size": stat.st_size, "mtime": stat.st_mtime_ns}
    return fingerprint


def checkpoint_path(prefix: str) -> Path:
    return CHECKPOINT_DIR / f"{prefix}.json"


def load_checkpoint(prefix: str) -> dict:
    """Load the run checkpoint for `prefix` ({} when absent or corrupt)."""
    path = checkpoint_path(prefix)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def checkpoint_matches_inputs(checkpoint: dict, assessment_file: str, png_path=None, csv_path=None) -> bool:
    """True when the checkpoint was created for the same input files (sizes/mtimes)."""
    return checkpoint.get("inputs") == _input_fingerprint(assessment_file, png_path, csv_path)


def save_task_checkpoint(prefix: str, task_name: str, raw: str, assessment_file: str, png_path=None, csv_path=None) -> None:
    """Persist one completed task's output under output/.checkpoints/<prefix>.json."""
    data = load_checkpoint(prefix)
    data.setdefault("tasks", {})[task_name] = {"raw": raw}
    data["inputs"] = _input_fingerprint(assessment_file, png_path, csv_path)
    path = checkpoint_path(prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def completed_tasks(checkpoint: dict) -> set[str]:
    """Names of tasks already checkpointed for this run."""
    return set((checkpoint.get("tasks") or {}).keys())


def get_task_output(checkpoint: dict, task_name: str) -> str:
    """Raw output text of a checkpointed task ('' when absent)."""
    task = (checkpoint.get("tasks") or {}).get(task_name)
    return (task or {}).get("raw", "")
