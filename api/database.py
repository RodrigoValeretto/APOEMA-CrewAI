"""
Database operations for APOEMA API
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import psycopg
from psycopg.rows import dict_row
from config import get_config
from .exceptions import (
    DatabaseError,
    AnalysisNotFound,
    CorpusNotFound,
    CorpusDocumentNotFound,
)
from .constants import AnalysisStatus


config = get_config()


def get_connection():
    """Get a database connection"""
    try:
        return psycopg.connect(
            host=config.DB_HOST,
            port=config.DB_PORT,
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            dbname=config.DB_NAME,
        )
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to connect to database: {str(e)}")


def create_analysis(
    analysis_type: str,
    status: str = AnalysisStatus.PENDING.value,
    model: Optional[str] = None,
    important_programs: Optional[List[str]] = None,
    corpus_id: Optional[int] = None,
    report_reference: Optional[str] = None,
) -> int:
    """
    Create a new analysis record

    Args:
        analysis_type: Type of analysis (pdf, png_csv, basic)
        status: Initial status (default: pending)
        model: LLM model used for the analysis (stored for retry support)
        important_programs: Program identifiers marked as important by the user
            (Sigla values from the plot CSV); stored for retry support
        corpus_id: Corpus (CAPES area) that sourced this analysis (optional)
        report_reference: Report identifier this analysis belongs to (optional)

    Returns:
        analysis_id

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analysis (type, status, model, important_programs, corpus_id, report_reference, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        analysis_type,
                        status,
                        model,
                        important_programs,
                        corpus_id,
                        report_reference,
                        datetime.now(),
                        datetime.now(),
                    ),
                )
                analysis_id = cur.fetchone()[0]
                conn.commit()
                return analysis_id
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to create analysis: {str(e)}")


def get_analysis(analysis_id: int) -> Dict[str, Any]:
    """
    Get analysis details by ID

    Args:
        analysis_id: ID of analysis

    Returns:
        Analysis record as dict

    Raises:
        AnalysisNotFound: If analysis doesn't exist
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, type, status, model, important_programs, corpus_id, report_reference, created_at, updated_at
                    FROM analysis
                    WHERE id = %s
                    """,
                    (analysis_id,),
                )
                result = cur.fetchone()
                if not result:
                    raise AnalysisNotFound(analysis_id)
                return dict(result)
    except AnalysisNotFound:
        raise
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analysis: {str(e)}")


def get_analyses_by_report(report_reference: str) -> List[Dict[str, Any]]:
    """
    Get all analyses that belong to a report (shared report_reference).

    Args:
        report_reference: Report identifier to look up

    Returns:
        List of analysis records (id, type, status, ...) ordered by id (creation order)

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, type, status, model, important_programs,
                           corpus_id, report_reference, created_at, updated_at
                    FROM analysis
                    WHERE report_reference = %s
                    ORDER BY id
                    """,
                    (report_reference,),
                )
                return [dict(row) for row in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analyses by report: {str(e)}")


def get_pending_analyses(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    List analyses still 'pending' in FIFO order (lowest id first).

    Used by the orphan-repair endpoint/watchdog: a 'pending' row whose
    RabbitMQ message was lost (a queue purge) blocks the FIFO gate forever,
    so this enumerates the candidates to re-enqueue.

    Args:
        limit: Optional cap on the number of rows returned (for bounded repair
            passes). None returns all pending rows.

    Returns:
        List of analysis dicts (id, type, status, model, important_programs,
        corpus_id, report_reference, created_at, updated_at) ordered by id.

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                query = """
                    SELECT id, type, status, model, important_programs,
                           corpus_id, report_reference, created_at, updated_at
                    FROM analysis
                    WHERE status = 'pending'
                    ORDER BY id
                """
                if limit:
                    query += " LIMIT %s"
                    cur.execute(query, (limit,))
                else:
                    cur.execute(query)
                return [dict(row) for row in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to list pending analyses: {str(e)}")


def get_report_png_urls(report_reference: str) -> set:
    """PNG source URLs already analyzed under a report (idempotent re-ingest).

    Used by the report-ingestion endpoint to skip charts that already have an
    analysis, so re-triggering the endpoint does not duplicate analyses.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT af.url
                    FROM analysis a
                    JOIN analysis_file_mapping afm ON afm.analysis_id = a.id
                    JOIN analysis_files af ON af.id = afm.file_id
                    WHERE a.report_reference = %s
                      AND af.file_type = 'png'
                      AND af.url IS NOT NULL
                    """,
                    (report_reference,),
                )
                return {row["url"] for row in cur.fetchall()}
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get report png urls: {str(e)}")


def get_all_analyses(
    skip: int = 0,
    limit: int = 10,
    analysis_type: Optional[str] = None,
    status: Optional[str] = None,
) -> tuple[int, List[Dict[str, Any]]]:
    """
    Get paginated list of analyses with optional filters

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        analysis_type: Filter by type (optional)
        status: Filter by status (optional)

    Returns:
        Tuple of (total_count, analyses_list)

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Build WHERE clause
                where_conditions = []
                params = []

                if analysis_type:
                    where_conditions.append("type = %s")
                    params.append(analysis_type)

                if status:
                    where_conditions.append("status = %s")
                    params.append(status)

                where_clause = ""
                if where_conditions:
                    where_clause = "WHERE " + " AND ".join(where_conditions)

                # Get total count
                count_query = f"SELECT COUNT(*) FROM analysis {where_clause}"
                cur.execute(count_query, params)
                total_count = cur.fetchone()["count"]

                # Get paginated results
                query = f"""
                    SELECT
                        id, type, status, created_at, updated_at, important_programs,
                        (SELECT COUNT(*) FROM analysis_results WHERE analysis_id = analysis.id) as results_count
                    FROM analysis
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([limit, skip])
                cur.execute(query, params)
                analyses = [dict(row) for row in cur.fetchall()]

                return total_count, analyses

    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analyses: {str(e)}")


def get_stale_processing_analyses(
    older_than_seconds: int,
) -> List[Dict[str, Any]]:
    """
    Find analyses stuck in 'processing' (or 'queued') for longer than a threshold.

    These are zombies: a crashed/stalled worker left the row in 'processing'
    with no live consumer, blocking the FIFO gate forever (failed/completed
    do not block, but processing/queued do).

    Args:
        older_than_seconds: Minimum age of the status (based on updated_at)

    Returns:
        List of analysis dicts (id, type, status, updated_at) that are stale
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, type, status, updated_at
                    FROM analysis
                    WHERE status IN ('processing', 'queued')
                      AND updated_at < %s
                    ORDER BY id
                    """,
                    (datetime.now() - timedelta(seconds=older_than_seconds),),
                )
                return [dict(r) for r in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to find stale analyses: {str(e)}")


def kill_zombie_analysis(analysis_id: int) -> Optional[Dict[str, Any]]:
    """
    Mark a zombie analysis as 'failed' so it no longer blocks the FIFO gate.

    Only transitions from 'processing'/'queued' (the states that block the
    gate). Returns the analysis row if it was a zombie and got killed, or None
    if the analysis is not in a zombie state (nothing to do).

    Args:
        analysis_id: ID of the analysis to kill

    Returns:
        The killed analysis row (dict) or None if not a zombie
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE analysis
                    SET status = 'failed', updated_at = %s
                    WHERE id = %s AND status IN ('processing', 'queued')
                    RETURNING id, type, status, updated_at
                    """,
                    (datetime.now(), analysis_id),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to kill zombie analysis: {str(e)}")


def update_analysis_status(analysis_id: int, new_status: str) -> None:
    """
    Update analysis status

    Args:
        analysis_id: ID of analysis
        new_status: New status value

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE analysis
                    SET status = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (new_status, datetime.now(), analysis_id),
                )
                conn.commit()
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to update analysis status: {str(e)}")


# Advisory lock key serializing the sequential-processing gate across ALL
# workers/processes. Any value works as long as every claimant uses the same.
_ANALYSIS_GATE_LOCK = 727001


def claim_analysis_for_processing(analysis_id: int) -> bool:
    """
    Atomically claim the single-processing slot for `analysis_id`.

    The gate is enforced with a Postgres advisory transaction lock plus a
    compare-and-swap on the status column, so concurrent workers can NEVER
    both observe "no one is processing" and both start (the check-then-act
    race the naive FIFO check suffered from).

    Succeeds only when:
      - the analysis is not already 'completed', and
      - no OTHER analysis is currently 'processing', and
      - no OLDER (lower-id) analysis is pending/processing/queued (FIFO).

    Returns True when the caller now owns the slot (status flipped to
    'processing'); False otherwise (caller must requeue through the gate).
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Serialize all claim attempts: only one worker passes this
                # point at a time, eliminating the check-then-act race.
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ANALYSIS_GATE_LOCK,))

                cur.execute(
                    "SELECT COUNT(*) FROM analysis WHERE status = 'processing' AND id != %s",
                    (analysis_id,),
                )
                processing_count = cur.fetchone()
                if processing_count is not None and processing_count[0] > 0:
                    return False

                cur.execute(
                    """
                    SELECT COUNT(*) FROM analysis
                    WHERE id < %s AND status IN ('pending', 'processing', 'queued')
                    """,
                    (analysis_id,),
                )
                older_count = cur.fetchone()
                if older_count is not None and older_count[0] > 0:
                    return False

                cur.execute(
                    """
                    UPDATE analysis
                    SET status = 'processing', updated_at = %s
                    WHERE id = %s AND status NOT IN ('completed', 'cancelled')
                    """,
                    (datetime.now(), analysis_id),
                )
                conn.commit()
                return cur.rowcount > 0
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to claim analysis slot: {str(e)}")


def save_analysis_result(
    analysis_id: int,
    task_name: str,
    result: str,
) -> int:
    """
    Save a task result to analysis_results table

    The raw result is post-processed: a JSON-object output is stored as the
    parsed object in ``result_json`` with ``result`` NULL; anything else keeps
    its raw text in ``result`` (``result_json`` NULL).

    Args:
        analysis_id: ID of the analysis
        task_name: Name of the task
        result: Result content

    Returns:
        result_id

    Raises:
        DatabaseError: If database operation fails
    """
    from .result_processing import split_result_json

    import json as _json

    result_text, result_json = split_result_json(result)
    # psycopg cannot adapt a raw Python dict to a JSONB column (it raises
    # "cannot adapt type 'dict'"); serialize it to a JSON string so the
    # placeholder binds correctly.
    result_json_param = _json.dumps(result_json) if result_json is not None else None
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Upsert: a resumed run re-reports tasks restored from the
                # checkpoint, so replace any previous row for this task instead
                # of accumulating duplicates.
                cur.execute(
                    "DELETE FROM analysis_results WHERE analysis_id = %s AND task_name = %s",
                    (analysis_id, task_name),
                )
                cur.execute(
                    """
                    INSERT INTO analysis_results (analysis_id, task_name, result, result_json, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (analysis_id, task_name, result_text, result_json_param, datetime.now()),
                )
                result_id = cur.fetchone()[0]
                conn.commit()
                return result_id
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to save analysis result: {str(e)}")


def get_analysis_results(
    analysis_id: int,
    task_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get all results for an analysis

    Args:
        analysis_id: ID of analysis
        task_name: Optional filter by task name

    Returns:
        List of result records

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_clause = "WHERE analysis_id = %s"
                params = [analysis_id]

                if task_name:
                    where_clause += " AND task_name = %s"
                    params.append(task_name)

                cur.execute(
                    f"""
                    SELECT id, analysis_id, task_name, result, result_json, created_at
                    FROM analysis_results
                    {where_clause}
                    ORDER BY created_at ASC
                    """,
                    params,
                )
                results = [dict(row) for row in cur.fetchall()]
                return results

    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analysis results: {str(e)}")


def delete_analysis(analysis_id: int) -> None:
    """
    Delete an analysis and its results (cascade)

    Args:
        analysis_id: ID of analysis to delete

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analysis WHERE id = %s", (analysis_id,))
                conn.commit()
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to delete analysis: {str(e)}")


def create_analysis_file(
    file_type: str,
    file_name: str,
    file_path: str,
    file_size: int,
    url: Optional[str] = None,
) -> int:
    """
    Create a file tracking record (without analysis association)

    Args:
        file_type: Type of file (assessment, pdf, png, csv)
        file_name: Original filename
        file_path: Path where file is stored
        file_size: File size in bytes
        url: Optional URL where the file was downloaded from (for deduplication)

    Returns:
        file_id

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analysis_files (file_type, file_name, file_path, file_size, url, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (file_type, file_name, file_path, file_size, url, datetime.now()),
                )
                file_id = cur.fetchone()[0]
                conn.commit()
                return file_id
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to create analysis file record: {str(e)}")


def get_analysis_file(file_id: int) -> Dict[str, Any]:
    """
    Get file tracking record by ID

    Args:
        file_id: ID of file record

    Returns:
        File record as dict

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, file_type, file_name, file_path, file_size, url, created_at
                    FROM analysis_files
                    WHERE id = %s
                    """,
                    (file_id,),
                )
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analysis file: {str(e)}")


def get_analysis_file_by_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Get file tracking record by URL (for deduplication)

    Args:
        url: URL of the file to find

    Returns:
        File record as dict, or None if not found

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, file_type, file_name, file_path, file_size, url, created_at
                    FROM analysis_files
                    WHERE url = %s
                    """,
                    (url,),
                )
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analysis file by URL: {str(e)}")


def delete_analysis_file(file_id: int) -> None:
    """
    Delete a file tracking record

    Args:
        file_id: ID of file record

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analysis_files WHERE id = %s", (file_id,))
                conn.commit()
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to delete analysis file: {str(e)}")


def create_analysis_file_mapping(
    analysis_id: int,
    file_id: int,
    file_type: str,
) -> int:
    """
    Create a mapping between an analysis and a file

    Args:
        analysis_id: ID of analysis
        file_id: ID of file
        file_type: Type of file (assessment, pdf, png, csv)

    Returns:
        mapping_id

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analysis_file_mapping (analysis_id, file_id, file_type, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (analysis_id, file_id, file_type, datetime.now()),
                )
                mapping_id = cur.fetchone()[0]
                conn.commit()
                return mapping_id
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to create analysis file mapping: {str(e)}")


def get_analysis_files(analysis_id: int) -> List[Dict[str, Any]]:
    """
    Get all files associated with an analysis

    Args:
        analysis_id: ID of analysis

    Returns:
        List of file records with their mapping information

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT af.id, af.file_type, af.file_name, af.file_path, af.file_size, af.url, af.created_at,
                           afm.file_type as mapping_file_type, afm.created_at as mapping_created_at
                    FROM analysis_files af
                    JOIN analysis_file_mapping afm ON af.id = afm.file_id
                    WHERE afm.analysis_id = %s
                    ORDER BY afm.created_at DESC
                    """,
                    (analysis_id,),
                )
                results = cur.fetchall()
                return [dict(row) for row in results]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get analysis files: {str(e)}")


def cleanup_orphaned_files() -> int:
    """
    Delete files that are not referenced by any analysis

    Returns:
        Number of files deleted

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Find and delete orphaned files
                cur.execute(
                    """
                    DELETE FROM analysis_files
                    WHERE id NOT IN (SELECT DISTINCT file_id FROM analysis_file_mapping)
                    """
                )
                deleted_count = cur.rowcount
                conn.commit()
                return deleted_count
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to cleanup orphaned files: {str(e)}")


def count_completed_results(analysis_id: int) -> int:
    """
    Count number of completed task results for an analysis

    Args:
        analysis_id: ID of analysis

    Returns:
        Count of results

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM analysis_results WHERE analysis_id = %s",
                    (analysis_id,),
                )
                count = cur.fetchone()[0]
                return count
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to count results: {str(e)}")


def count_processing_analyses(exclude_analysis_id: Optional[int] = None) -> int:
    """
    Count number of analyses currently being processed

    Args:
        exclude_analysis_id: Optional analysis ID to exclude from count (for checking if others are processing)

    Returns:
        Count of analyses in 'processing' status

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if exclude_analysis_id:
                    cur.execute(
                        "SELECT COUNT(*) FROM analysis WHERE status = 'processing' AND id != %s",
                        (exclude_analysis_id,),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM analysis WHERE status = 'processing'"
                    )
                count = cur.fetchone()[0]
                return count
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to count processing analyses: {str(e)}")


def count_pending_analyses() -> int:
    """Count analyses in 'pending' status.

    Used by the orphan-repair watchdog to detect a deadlocked gate (pending > 0
    with processing == 0, the signature of orphaned pending rows).
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM analysis WHERE status = 'pending'")
                count = cur.fetchone()[0]
                return count
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to count pending analyses: {str(e)}")


def cancel_pending_analyses() -> int:
    """Mark every 'pending' analysis as 'cancelled' (terminal, non-blocking).

    Used by the cancel-pending endpoint: a user wants to clear the queue WITHOUT
    running it. 'cancelled' is a terminal status the FIFO gate ignores and the
    run actor's idempotency guard drops, so a residual message re-delivered
    later can never execute a cancelled analysis (unlike 'failed', which the
    claim accepts for retry/resume).

    Returns the number of rows transitioned.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE analysis
                    SET status = 'cancelled', updated_at = %s
                    WHERE status = 'pending'
                    """,
                    (datetime.now(),),
                )
                conn.commit()
                return cur.rowcount
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to cancel pending analyses: {str(e)}")


def count_older_pending_analyses(analysis_id: int) -> int:
    """
    Count number of analyses that are older (lower ID) and still pending/processing

    This enforces FIFO ordering: an analysis can only be processed if all older
    analyses have already been completed.

    Args:
        analysis_id: ID of current analysis to check

    Returns:
        Count of analyses with lower IDs that are not completed

    Raises:
        DatabaseError: If database operation fails
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM analysis
                    WHERE id < %s
                    AND status IN ('pending', 'processing', 'queued')
                    """,
                    (analysis_id,),
                )
                count = cur.fetchone()[0]
                return count
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to count older pending analyses: {str(e)}")


# ---------------------------------------------------------------------------
# Corpora (CAPES area document corpus) + conversion documents
# ---------------------------------------------------------------------------

_DOC_SELECT = """
    SELECT d.id, d.corpus_id, d.kind, d.status, d.error,
           d.original_file_id, d.converted_file_id,
           d.drive_file_id,
           d.created_at, d.updated_at,
           fo.file_name AS original_file_name, fo.file_path AS original_file_path,
           fo.file_size AS original_file_size,
           fc.file_name AS converted_file_name, fc.file_path AS converted_file_path,
           fc.file_size AS converted_file_size
    FROM corpus_documents d
    LEFT JOIN analysis_files fo ON fo.id = d.original_file_id
    LEFT JOIN analysis_files fc ON fc.id = d.converted_file_id
"""


def create_corpus(name: str, slug: str, quadrennium: Optional[str] = None) -> int:
    """Create a corpus (CAPES area corpus). Raises DatabaseError if slug exists."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO corpora (name, slug, quadrennium, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (name, slug, quadrennium, datetime.now()),
                )
                row = cur.fetchone()
                corpus_id = row[0] if row else None
                conn.commit()
                return corpus_id
    except psycopg.errors.UniqueViolation:
        raise DatabaseError(f"Corpus with slug '{slug}' already exists")
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to create corpus: {str(e)}")


def get_corpus(corpus_id: int) -> Dict[str, Any]:
    """Get a corpus row (raises CorpusNotFound)."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, slug, quadrennium, created_at
                    FROM corpora WHERE id = %s
                    """,
                    (corpus_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise CorpusNotFound(corpus_id)
                return dict(row)
    except CorpusNotFound:
        raise
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get corpus: {str(e)}")


def get_corpus_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Get a corpus row by slug, or None if it does not exist."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, slug, quadrennium, created_at
                    FROM corpora WHERE slug = %s
                    """,
                    (slug,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get corpus by slug: {str(e)}")


def list_corpora() -> List[Dict[str, Any]]:
    """List all corpora (newest first) with document counts."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT i.id, i.name, i.slug, i.quadrennium, i.created_at,
                           COUNT(d.id) AS total_documents,
                           COUNT(d.id) FILTER (WHERE d.status = 'completed') AS completed_documents
                    FROM corpora i
                    LEFT JOIN corpus_documents d ON d.corpus_id = i.id
                    GROUP BY i.id
                    ORDER BY i.id DESC
                    """
                )
                return [dict(r) for r in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to list corpora: {str(e)}")


def create_corpus_document(
    corpus_id: int,
    kind: str,
    original_file_id: int,
    drive_file_id: Optional[str] = None,
) -> int:
    """Register a document upload inside a corpus (status: pending)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO corpus_documents
                        (corpus_id, kind, status, original_file_id, drive_file_id, created_at, updated_at)
                    VALUES (%s, %s, 'pending', %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        corpus_id,
                        kind,
                        original_file_id,
                        drive_file_id,
                        datetime.now(),
                        datetime.now(),
                    ),
                )
                row = cur.fetchone()
                doc_id = row[0] if row else None
                conn.commit()
                return doc_id
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to create corpus document: {str(e)}")


def get_corpus_document_by_drive_file_id(
    drive_file_id: str,
) -> Optional[Dict[str, Any]]:
    """Get a document by its Google Drive file id, or None (dedupe)."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_DOC_SELECT + " WHERE d.drive_file_id = %s", (drive_file_id,))
                row = cur.fetchone()
                return dict(row) if row else None
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get document by drive file id: {str(e)}")


def get_corpus_document(document_id: int) -> Dict[str, Any]:
    """Get a document row joined with source/converted file info."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_DOC_SELECT + " WHERE d.id = %s", (document_id,))
                row = cur.fetchone()
                if not row:
                    raise CorpusDocumentNotFound(document_id)
                return dict(row)
    except CorpusDocumentNotFound:
        raise
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get corpus document: {str(e)}")


def list_corpus_documents(corpus_id: int) -> List[Dict[str, Any]]:
    """List documents of a corpus (oldest first)."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    _DOC_SELECT + " WHERE d.corpus_id = %s ORDER BY d.id",
                    (corpus_id,),
                )
                return [dict(r) for r in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to list corpus documents: {str(e)}")


def claim_corpus_document(document_id: int) -> bool:
    """Atomically claim a pending document for conversion (pending -> processing).

    Returns True if this caller won the claim; False if the document is already
    being processed or was already converted. A 'failed' document is
    re-claimable (the drive ingestion re-enqueues it to retry); a document stuck
    in 'processing' for over 30 minutes (crashed worker mid-conversion) can be
    reclaimed — mirrors the analysis zombie-recovery lesson.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE corpus_documents
                    SET status = 'processing', updated_at = %s
                    WHERE id = %s
                      AND (
                        status = 'pending'
                        OR status = 'failed'
                        OR (status = 'processing'
                            AND updated_at < %s - INTERVAL '30 minutes')
                      )
                    """,
                    (datetime.now(), document_id, datetime.now()),
                )
                claimed = cur.rowcount > 0
                conn.commit()
                return claimed
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to claim corpus document: {str(e)}")


def update_corpus_document_status(
    document_id: int,
    status: str,
    converted_file_id: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Update document conversion status (completed/failed + artifacts)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE corpus_documents
                    SET status = %s, converted_file_id = %s, error = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (status, converted_file_id, error, datetime.now(), document_id),
                )
                conn.commit()
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to update corpus document status: {str(e)}")


def get_completed_documents_by_kinds(
    corpus_id: int, kinds: List[str]
) -> List[Dict[str, Any]]:
    """Completed converted documents of the given kinds (for analysis input)."""
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    _DOC_SELECT
                    + """
                      WHERE d.corpus_id = %s
                        AND d.kind = ANY(%s)
                        AND d.status = 'completed'
                        AND d.converted_file_id IS NOT NULL
                      ORDER BY d.id
                      """,
                    (corpus_id, list(kinds)),
                )
                return [dict(r) for r in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get corpus converted documents: {str(e)}")


def get_area_rows() -> List[Dict[str, Any]]:
    """Area rows: per corpus, its latest form document (or NULLs).

    Returns one row per corpus (joined to its most recent ``kind='form'``
    document), keyed by slug. Corpora without a form document yet still
    appear with NULL document fields — the areas endpoint overlays the static
    catalog on top of this.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (i.id)
                           i.id AS corpus_id,
                           i.slug,
                           i.quadrennium,
                           d.id AS document_id,
                           d.status,
                           d.converted_file_id,
                           d.drive_file_id
                    FROM corpora i
                    LEFT JOIN corpus_documents d
                           ON d.corpus_id = i.id AND d.kind = 'form'
                    ORDER BY i.id, d.id DESC NULLS LAST
                    """
                )
                return [dict(r) for r in cur.fetchall()]
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get area rows: {str(e)}")


def get_report_status_counts(report_reference: str) -> Dict[str, int]:
    """Count a report's analyses grouped by status.

    Returns a ``{status: count}`` dict (empty when the report has no analyses).
    """
    try:
        with get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM analysis
                    WHERE report_reference = %s
                    GROUP BY status
                    """,
                    (report_reference,),
                )
                return {r["status"]: r["count"] for r in cur.fetchall()}
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to get report status counts: {str(e)}")


def delete_analyses_by_report(report_reference: str) -> List[int]:
    """Delete every analysis of a report (cascade clears results + mappings).

    Returns the deleted analysis ids so the caller can clean up the per-chart
    files and run checkpoints. ``analysis_files`` rows are NOT touched here —
    the caller deletes the PNG/CSV assets explicitly after the cascade.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM analysis WHERE report_reference = %s",
                    (report_reference,),
                )
                ids = [r[0] for r in cur.fetchall()]
                cur.execute(
                    "DELETE FROM analysis WHERE report_reference = %s",
                    (report_reference,),
                )
                conn.commit()
                return ids
    except psycopg.Error as e:
        raise DatabaseError(f"Failed to delete analyses by report: {str(e)}")
