"""
Dramatiq tasks for async processing of APOEMA analysis

The workflow:
1. Task creates an 'analysis' record in the database
2. The analysis_id is passed to the CrewAI flow/crew
3. As tasks complete, results are inserted into 'analysis_results' using save_analysis_result()
4. The analysis status is updated based on completion
"""
import dramatiq
from dramatiq.brokers.rabbitmq import RabbitMQBroker
import psycopg
import os
from datetime import datetime
import json
import asyncio
from apoema_flow import run_apoema_flow
from apoema_agent import run_apoema_pipeline

# Configure RabbitMQ broker
rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672//")
broker = RabbitMQBroker(url=rabbitmq_url)
dramatiq.set_broker(broker)


def get_db_connection():
    """Get PostgreSQL connection"""
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        user=os.getenv("DB_USER", "apoema"),
        password=os.getenv("DB_PASSWORD", "apoema_dev_password"),
        dbname=os.getenv("DB_NAME", "apoema_db"),
    )


def save_analysis_result(analysis_id: int, task_name: str, result: str) -> None:
    """
    Save an analysis result to the database.

    This function is called by CrewAI tasks as they complete.

    Args:
        analysis_id: The ID of the analysis this result belongs to
        task_name: Name of the task that produced this result
        result: The result text/output
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analysis_results (analysis_id, task_name, result, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    analysis_id,
                    task_name,
                    result,
                    datetime.now()
                )
            )
            conn.commit()


def update_analysis_status(analysis_id: int, status: str) -> None:
    """
    Update the status of an analysis.

    Args:
        analysis_id: The ID of the analysis to update
        status: The new status (pending, processing, completed, failed)
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE analysis
                SET status = %s, updated_at = %s
                WHERE id = %s
                """,
                (status, datetime.now(), analysis_id)
            )
            conn.commit()


@dramatiq.actor(store_results=True, max_retries=0)
def run_analysis_flow(
    assessment_file: str,
    pdf_file: str = None,
    png_file: str = None,
    csv_file: str = None,
    output_prefix: str = None,
    model: str = "gemini",
) -> dict:
    """
    Async task to run APOEMA Flow analysis.

    This task:
    1. Creates an 'analysis' record in the database
    2. Runs the CrewAI flow
    3. CrewAI tasks will call save_analysis_result() to store results
    4. Updates the analysis status on completion

    Args:
        assessment_file: Path to assessment JSON file
        pdf_file: Path to PDF report file (optional)
        png_file: Path to PNG image file (optional)
        csv_file: Path to CSV data file (optional)
        output_prefix: Prefix for output files
        model: Model to use (gemini, ollama)

    Returns:
        Dictionary with analysis info
    """
    analysis_id = None

    try:
        # Create analysis record in database
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                workflow_type = "pdf" if pdf_file else ("png_csv" if png_file and csv_file else "basic")
                cur.execute(
                    """
                    INSERT INTO analysis (type, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (workflow_type, "processing", datetime.now(), datetime.now())
                )
                analysis_id = cur.fetchone()[0]
                conn.commit()

        # Run the APOEMA Flow (pass analysis_id via environment or context)
        os.environ["ANALYSIS_ID"] = str(analysis_id)

        result = asyncio.run(
            run_apoema_flow(
                assessment_file=assessment_file,
                pdf_path=pdf_file,
                output_prefix=output_prefix,
                png_path=png_file,
                csv_path=csv_file,
                model=model,
            )
        )

        # Update analysis status to completed
        update_analysis_status(analysis_id, "completed")

        return {
            "analysis_id": analysis_id,
            "status": "completed",
            "message": "APOEMA Flow analysis completed successfully",
        }

    except Exception as e:
        # Update analysis status to failed
        if analysis_id:
            update_analysis_status(analysis_id, "failed")
            save_analysis_result(
                analysis_id,
                "run_analysis_flow_error",
                f"Error: {str(e)}"
            )

        raise e


@dramatiq.actor(store_results=True, max_retries=0)
def run_analysis_crew(
    assessment_file: str,
    pdf_file: str = None,
    output_prefix: str = None,
    png_file: str = None,
    csv_file: str = None,
    model: str = "gemini",
) -> dict:
    """
    Async task to run APOEMA Crew (traditional) analysis.

    This task:
    1. Creates an 'analysis' record in the database
    2. Runs the CrewAI crew pipeline
    3. CrewAI tasks will call save_analysis_result() to store results
    4. Updates the analysis status on completion

    Args:
        assessment_file: Path to assessment JSON file
        pdf_file: Path to PDF report file (optional)
        output_prefix: Prefix for output files
        png_file: Path to PNG image file (optional)
        csv_file: Path to CSV data file (optional)
        model: Model to use (gemini, ollama)

    Returns:
        Dictionary with analysis info
    """
    analysis_id = None

    try:
        # Create analysis record in database
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                workflow_type = "pdf" if pdf_file else ("png_csv" if png_file and csv_file else "basic")
                cur.execute(
                    """
                    INSERT INTO analysis (type, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (workflow_type, "processing", datetime.now(), datetime.now())
                )
                analysis_id = cur.fetchone()[0]
                conn.commit()

        # Run the APOEMA Crew (pass analysis_id via environment or context)
        os.environ["ANALYSIS_ID"] = str(analysis_id)

        result = run_apoema_pipeline(
            assessment_file=assessment_file,
            pdf_path=pdf_file,
            output_prefix=output_prefix,
            png_path=png_file,
            csv_path=csv_file,
            model=model,
        )

        # Update analysis status to completed
        update_analysis_status(analysis_id, "completed")

        return {
            "analysis_id": analysis_id,
            "status": "completed",
            "message": "APOEMA Crew analysis completed successfully",
        }

    except Exception as e:
        # Update analysis status to failed
        if analysis_id:
            update_analysis_status(analysis_id, "failed")
            save_analysis_result(
                analysis_id,
                "run_analysis_crew_error",
                f"Error: {str(e)}"
            )

        raise e