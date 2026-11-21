"""Repair orphaned 'pending' analyses whose RabbitMQ messages were lost.

A queue purge (manual `rabbitmqctl purge_queue default`, or the zombie-kill
blanket purge) deletes messages while their rows stay 'pending' in the DB.
Those rows have no driving message, so the FIFO gate
(`count_older_pending_analyses`) blocks every analysis behind them forever:
every later analysis sees the orphan as an "older pending" and requeues in a
tight backoff loop, while `processing` stays 0 — a livelock, not a crash.

This module rebuilds each orphan's inputs from `analysis_file_mapping` (the
same source the retry endpoint reads) and re-enqueues it through the gate. The
gate actor's idempotency guard (tasks.py) drops any duplicate message, so
re-enqueueing an analysis that still HAS a message is safe — it cannot double
execute.
"""
import logging
import os
from typing import Dict, Optional

from . import database
from .constants import CONVERTED_EXTRA_FILE_TYPE, FileType
from .exceptions import InvalidAnalysisInput

logger = logging.getLogger(__name__)


def rebuild_analysis_inputs(analysis_id: int) -> Dict:
    """Rebuild an analysis's input paths + knowledge files from its mappings.

    Returns a dict with keys assessment_file, pdf_file, png_file, csv_file and
    knowledge_files (a list). Raises InvalidAnalysisInput if the assessment
    source has no mapping or any input file is gone from disk.
    """
    files = database.get_analysis_files(analysis_id)
    paths = {}
    knowledge_files = []
    for f in files:
        ft = f["file_type"]
        if ft == CONVERTED_EXTRA_FILE_TYPE:
            knowledge_files.append(f["file_path"])
        elif ft not in paths:
            paths[ft] = f["file_path"]

    assessment_file = paths.get(FileType.ASSESSMENT.value)
    if not assessment_file:
        raise InvalidAnalysisInput(
            f"Analysis {analysis_id} has no assessment file mapping; cannot repair"
        )

    for label, path in (
        ("assessment", assessment_file),
        ("pdf", paths.get(FileType.PDF.value)),
        ("png", paths.get(FileType.PNG.value)),
        ("csv", paths.get(FileType.CSV.value)),
    ):
        if path and not os.path.exists(path):
            raise InvalidAnalysisInput(
                f"Input file for '{label}' no longer exists: {path}"
            )
    for kf in knowledge_files:
        if not os.path.exists(kf):
            raise InvalidAnalysisInput(f"Knowledge file no longer exists: {kf}")

    return {
        "assessment_file": assessment_file,
        "pdf_file": paths.get(FileType.PDF.value) or "",
        "png_file": paths.get(FileType.PNG.value) or "",
        "csv_file": paths.get(FileType.CSV.value) or "",
        "knowledge_files": knowledge_files,
    }


def repair_orphaned_pending(max_count: Optional[int] = None) -> Dict:
    """Re-enqueue every 'pending' analysis in FIFO order.

    Safe to call repeatedly: the gate actor's idempotency guard drops duplicate
    messages for analyses already running/done, and checkpoint/resume keeps any
    remaining re-execution idempotent.

    Args:
        max_count: Optional cap on how many analyses to re-enqueue in one pass.

    Returns:
        {"checked": N, "reenqueued": N, "skipped": [{id, reason}, ...]}
    """
    # Lazy import: `tasks` imports report_service, and this module is imported
    # by api (the endpoint), so importing tasks at module top would cycle.
    from tasks import enqueue_analysis_for_sequential_processing

    pending = database.get_pending_analyses(limit=max_count)
    reenqueued = 0
    skipped = []
    for a in pending:
        try:
            inputs = rebuild_analysis_inputs(a["id"])
        except InvalidAnalysisInput as e:
            skipped.append({"id": a["id"], "reason": str(e)})
            continue
        enqueue_analysis_for_sequential_processing.send(
            analysis_id=a["id"],
            assessment_file=inputs["assessment_file"],
            pdf_file=inputs["pdf_file"],
            png_file=inputs["png_file"],
            csv_file=inputs["csv_file"],
            output_prefix=f"analysis_{a['id']}",
            model=a.get("model") or "ollama",
            important_programs=a.get("important_programs") or [],
            knowledge_files=inputs["knowledge_files"],
        )
        reenqueued += 1
    return {
        "checked": len(pending),
        "reenqueued": reenqueued,
        "skipped": skipped,
    }


def gate_is_deadlocked() -> bool:
    """True when pending analyses exist but nothing is processing.

    That is the signature of orphaned pending rows blocking the FIFO gate:
    with a healthy queue the gate always has one analysis 'processing' (or the
    queue drains to zero). A persistent `processing == 0` while `pending > 0`
    means the head of the queue can never claim its slot.
    """
    return (
        database.count_processing_analyses() == 0
        and database.count_pending_analyses() > 0
    )


def run_orphan_repair_once(max_count: Optional[int] = None) -> Dict:
    """One watchdog pass: repair orphaned pending analyses if the gate is stuck.

    Never raises — the API watchdog loop calls this in a background task. When
    the gate is NOT deadlocked (an analysis is processing, or the queue is
    empty) it does nothing and returns a no-op summary.
    """
    try:
        if not gate_is_deadlocked():
            return {"deadlocked": False, "reenqueued": 0, "checked": 0, "skipped": []}
        result = repair_orphaned_pending(max_count=max_count)
        result["deadlocked"] = True
        return result
    except Exception as e:
        logger.exception("Orphan repair pass failed: %s", e)
        return {
            "deadlocked": False,
            "reenqueued": 0,
            "checked": 0,
            "skipped": [],
            "error": str(e),
        }


def cancel_pending(purge: bool = True) -> Dict:
    """Clear the queue WITHOUT running it: cancel pending analyses + purge.

    Marks every 'pending' analysis 'cancelled' (a terminal status the gate and
    the run actor ignore) and purges the analysis queues so no residual message
    survives to re-deliver. Safe even if a message does re-deliver: the run
    actor's idempotency guard drops 'cancelled' and the claim's CAS excludes it.

    Returns {"cancelled": N, "purged_messages": N}.
    """
    from zombie_kill import purge_analysis_queues

    purged = purge_analysis_queues() if purge else 0
    cancelled = database.cancel_pending_analyses()
    return {"cancelled": cancelled, "purged_messages": purged}
