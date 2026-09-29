"""
Zombie analysis cleanup: shared logic for the zombie-kill endpoints and the
automatic watchdog.

A zombie is an analysis stuck in 'processing'/'queued' whose worker died or
stalled mid-run (e.g. a runaway generation with no token cap stalling the
worker before it could ack the message). Zombies block the FIFO gate forever
because `claim_analysis_for_processing` counts every 'processing'/'queued'
row. The recovery is:

1. Mark the row 'failed' (failed does NOT block the gate).
2. Purge the RabbitMQ 'default' queue so any re-delivered orphan message for
   that analysis stops looping (a re-delivered message would resurrect the
   analysis back to 'processing' — the resurrection trap).
"""
import logging
import os

import pika

from api import database
from api.constants import AnalysisStatus

logger = logging.getLogger(__name__)

# Queues that may carry orphaned analysis messages. The analysis queue is
# 'default'; the delayed/dead-letter queues are purged too so phantom messages
# don't get re-delivered later.
ANALYSIS_QUEUES = ("default", "default.DQ", "default.XQ")


def _purge_queue(channel, queue_name: str) -> int:
    """Purge one queue, returning the number of purged messages (0 if absent)."""
    try:
        # Declare with passive=True first so an absent queue doesn't create it.
        channel.queue_declare(queue=queue_name, passive=True)
        method = channel.queue_purge(queue=queue_name)
        return method.method.message_count
    except Exception:
        # Queue does not exist or channel issue — nothing to purge.
        logger.debug("Queue %s not purgeable; nothing purged", queue_name)
        return 0


def purge_analysis_queues() -> int:
    """
    Purge all analysis-related RabbitMQ queues.

    Returns the total number of messages purged. Uses the same broker URL as
    the dramatiq broker (DRAMATIQ_BROKER_URL / RABBITMQ_URL).
    """
    broker_url = (
        os.getenv("DRAMATIQ_BROKER_URL")
        or os.getenv("RABBITMQ_URL")
        or "amqp://guest:guest@rabbitmq:5672/"
    )
    try:
        connection = pika.BlockingConnection(pika.URLParameters(broker_url))
        channel = connection.channel()
        total = 0
        for queue_name in ANALYSIS_QUEUES:
            total += _purge_queue(channel, queue_name)
        connection.close()
        return total
    except Exception as e:  # connection failures must not break the API
        logger.warning("Failed to purge RabbitMQ queues: %s", e)
        return 0


def kill_zombie_analysis(analysis_id: int, purge: bool = True) -> dict:
    """
    Kill a single zombie analysis: mark it failed (and purge the queues).

    Args:
        analysis_id: The analysis to kill.
        purge: Whether to also purge the RabbitMQ queues (default True).

    Returns:
        {"killed": bool, "analysis_id": int, "purged_messages": int}

    The analysis must currently be 'processing'/'queued' to be killed; a
    completed/failed/pending analysis is left alone (killed=False).
    """
    row = database.kill_zombie_analysis(analysis_id)
    if not row:
        return {
            "killed": False,
            "analysis_id": analysis_id,
            "purged_messages": 0,
        }
    purged = purge_analysis_queues() if purge else 0
    logger.info(
        "Zombie analysis %s killed (%s), purged %d queue messages",
        analysis_id,
        row["status"],
        purged,
    )
    return {
        "killed": True,
        "analysis_id": analysis_id,
        "purged_messages": purged,
    }


def cleanup_zombies(older_than_seconds: int, purge: bool = True) -> dict:
    """
    Kill every zombie analysis older than a threshold.

    Args:
        older_than_seconds: Minimum age (based on updated_at) to consider a
            'processing'/'queued' analysis a zombie.
        purge: Whether to also purge the RabbitMQ queues.

    Returns:
        {"killed": [analysis ids], "purged_messages": int, "checked": N}
    """
    stale = database.get_stale_processing_analyses(older_than_seconds)
    killed_ids = []
    for analysis in stale:
        row = database.kill_zombie_analysis(analysis["id"])
        if row:
            killed_ids.append(analysis["id"])
    purged = purge_analysis_queues() if (purge and killed_ids) else 0
    if killed_ids:
        logger.info(
            "Zombie cleanup killed %s (ids=%s), purged %d queue messages",
            len(killed_ids),
            killed_ids,
            purged,
        )
    return {
        "killed": killed_ids,
        "purged_messages": purged,
        "checked": len(stale),
    }


def run_watchdog_once(
    older_than_seconds: int,
    purge: bool = True,
) -> dict:
    """
    One watchdog pass: kill zombies and return the cleanup summary.
    Never raises — the API watchdog loop calls this in a background task.
    """
    try:
        return cleanup_zombies(older_than_seconds, purge=purge)
    except Exception as e:
        logger.exception("Watchdog cleanup failed: %s", e)
        return {"killed": [], "purged_messages": 0, "checked": 0, "error": str(e)}
