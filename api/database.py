"""
Database operations for APOEMA API
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
import psycopg
from psycopg.rows import dict_row
from config import get_config
from .exceptions import DatabaseError, AnalysisNotFound
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
) -> int:
    """
    Create a new analysis record

    Args:
        analysis_type: Type of analysis (pdf, png_csv, basic)
        status: Initial status (default: pending)
        model: LLM model used for the analysis (stored for retry support)
        important_programs: Program identifiers marked as important by the user
            (Sigla values from the plot CSV); stored for retry support

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
                    INSERT INTO analysis (type, status, model, important_programs, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        analysis_type,
                        status,
                        model,
                        important_programs,
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
                    SELECT id, type, status, model, important_programs, created_at, updated_at
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
                    WHERE id = %s AND status != 'completed'
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

    Args:
        analysis_id: ID of the analysis
        task_name: Name of the task
        result: Result content

    Returns:
        result_id

    Raises:
        DatabaseError: If database operation fails
    """
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
                    INSERT INTO analysis_results (analysis_id, task_name, result, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (analysis_id, task_name, result, datetime.now()),
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
                    SELECT id, analysis_id, task_name, result, created_at
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
