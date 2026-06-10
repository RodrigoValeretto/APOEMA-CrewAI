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


def create_analysis(analysis_type: str, status: str = AnalysisStatus.PENDING.value) -> int:
    """
    Create a new analysis record

    Args:
        analysis_type: Type of analysis (pdf, png_csv, basic)
        status: Initial status (default: pending)

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
                    INSERT INTO analysis (type, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (analysis_type, status, datetime.now(), datetime.now()),
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
                    SELECT id, type, status, created_at, updated_at
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
                        id, type, status, created_at, updated_at,
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
    analysis_id: Optional[int],
    file_type: str,
    file_name: str,
    file_path: str,
    file_size: int,
) -> int:
    """
    Create a file tracking record

    Args:
        analysis_id: Optional analysis ID
        file_type: Type of file (assessment, pdf, png, csv)
        file_name: Original filename
        file_path: Path where file is stored
        file_size: File size in bytes

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
                    INSERT INTO analysis_files (analysis_id, file_type, file_name, file_path, file_size, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (analysis_id, file_type, file_name, file_path, file_size, datetime.now()),
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
                    SELECT id, analysis_id, file_type, file_name, file_path, file_size, created_at
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
