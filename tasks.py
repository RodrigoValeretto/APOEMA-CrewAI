"""
Dramatiq tasks for async processing of APOEMA analysis

The workflow:
1. API creates 'analysis' record and sends Dramatiq task with analysis_id
2. Task receives analysis_id and creates callback function
3. Task runs CrewAI flow with callback
4. Each task completion in flow triggers callback → saves result to DB
5. Task updates final status to 'completed' or 'failed'
"""
import os
import dramatiq
from datetime import datetime
import traceback
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configure RabbitMQ broker BEFORE defining actors
# This must happen before @dramatiq.actor decorators are processed
from dramatiq.brokers.rabbitmq import RabbitmqBroker

rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")

# Configure RabbitMQ broker
# Using URL parameter is simplest and avoids pika parameter conflicts
broker = RabbitmqBroker(
    url=rabbitmq_url,
)
dramatiq.set_broker(broker)

# Now import the modules that use dramatiq
from apoema_flow import run_apoema_flow
from apoema_agent import run_apoema_pipeline
from db_manager import (
    update_analysis_status,
    save_analysis_result,
    count_processing_analyses,
    count_older_pending_analyses,
)


@dramatiq.actor(
    max_retries=10,  # Increased retries for queue management (10 retries with backoff = good time buffer)
    time_limit=30000,  # 30 seconds timeout for the queueing logic
    min_backoff=2000,   # 2 seconds initial backoff
    max_backoff=30000,  # 30 seconds max backoff
    priority=10,        # Higher priority for queue management
)
def enqueue_analysis_for_sequential_processing(
    analysis_id: int,
    assessment_file: str,
    pdf_file: str = None,
    png_file: str = None,
    csv_file: str = None,
    output_prefix: str = None,
    model: str = "ollama",
    important_programs: list = None,
) -> dict:
    """
    Intermediate task that manages sequential processing of analyses.

    This task ensures only ONE analysis is processing at a time:
    1. Checks if any OTHER analysis is currently processing
    2. If not → marks this analysis as processing and calls run_analysis_flow_with_tracking
    3. If yes → requeues itself with a delay (exponential backoff)

    This prevents multiple analyses from running concurrently by using database state
    as a coordination point, without modifying the database schema.

    Args:
        analysis_id: ID of analysis (created by API)
        assessment_file: Path to assessment JSON file
        pdf_file: Path to PDF report file (optional)
        png_file: Path to PNG image file (optional)
        csv_file: Path to CSV data file (optional)
        output_prefix: Prefix for output files
        model: Model to use (gemini, ollama)
        important_programs: Programs marked as important by the user (Sigla
            values from the plot CSV)

    Returns:
        Dictionary with queue status or result of actual processing
    """
    try:
        logger.info(f"[Analysis {analysis_id}] Checking sequential processing queue (FIFO)...")

        # Check 1: If any OTHER analysis is currently processing
        processing_count = count_processing_analyses(exclude_analysis_id=analysis_id)

        # Check 2: FIFO ordering - if there are older (lower ID) analyses still pending/processing
        older_pending_count = count_older_pending_analyses(analysis_id)

        if processing_count > 0 or older_pending_count > 0:
            # Either another analysis is processing OR there are older analyses waiting
            # Requeue this one with delay
            reason = ""
            if processing_count > 0:
                reason = f"{processing_count} analysis(es) currently processing"
            if older_pending_count > 0:
                if reason:
                    reason += f" and {older_pending_count} older analysis(es) pending"
                else:
                    reason = f"{older_pending_count} older analysis(es) pending (FIFO)"

            logger.info(
                f"[Analysis {analysis_id}] {reason}. "
                f"Requeuing with exponential backoff..."
            )
            # Requeue by calling itself again - Dramatiq will apply backoff
            enqueue_analysis_for_sequential_processing.send_with_options(
                kwargs={
                    "analysis_id": analysis_id,
                    "assessment_file": assessment_file,
                    "pdf_file": pdf_file,
                    "png_file": png_file,
                    "csv_file": csv_file,
                    "output_prefix": output_prefix,
                    "model": model,
                    "important_programs": important_programs,
                },
                delay=2000,  # 2 second delay before retry (Dramatiq will add exponential backoff)
            )
            return {
                "analysis_id": analysis_id,
                "status": "queued",
                "message": f"Queued for processing. {reason}",
            }

        # No other analysis processing, proceed with actual processing
        logger.info(f"[Analysis {analysis_id}] Queue is clear, starting processing...")
        result = run_analysis_flow_with_tracking.send(
            analysis_id=analysis_id,
            assessment_file=assessment_file,
            pdf_file=pdf_file,
            png_file=png_file,
            csv_file=csv_file,
            output_prefix=output_prefix,
            model=model,
            important_programs=important_programs,
        )

        return {
            "analysis_id": analysis_id,
            "status": "processing",
            "message": "Analysis started processing",
        }

    except Exception as e:
        logger.error(f"[Analysis {analysis_id}] ✗ Queue management failed: {str(e)}")
        logger.error(f"[Analysis {analysis_id}] Traceback:\n{traceback.format_exc()}")
        # Still try to process - don't let queueing fail the analysis
        logger.info(f"[Analysis {analysis_id}] Attempting direct processing despite queueing error...")
        result = run_analysis_flow_with_tracking.send(
            analysis_id=analysis_id,
            assessment_file=assessment_file,
            pdf_file=pdf_file,
            png_file=png_file,
            csv_file=csv_file,
            output_prefix=output_prefix,
            model=model,
            important_programs=important_programs,
        )
        return {
            "analysis_id": analysis_id,
            "status": "processing",
            "message": "Analysis started processing (after queueing error)",
        }


@dramatiq.actor(
    max_retries=2,
    time_limit=7200000,  # 120 minutes (covers full 5-task flow even on a loaded/slow host)
    min_backoff=1000,   # 1 second
    max_backoff=30000,  # 30 seconds
    priority=0,         # Normal priority
)
def run_analysis_flow_with_tracking(
    analysis_id: int,
    assessment_file: str,
    pdf_file: str = None,
    png_file: str = None,
    csv_file: str = None,
    output_prefix: str = None,
    model: str = "ollama",
    important_programs: list = None,
) -> dict:
    """
    Async task to run APOEMA Flow analysis with database tracking.

    This task:
    1. Receives analysis_id (already created in DB via API)
    2. Updates status to 'processing'
    3. Creates callback that saves results to DB
    4. Runs the CrewAI flow with callback
    5. Each task completion triggers callback → INSERT analysis_results
    6. Updates final status to 'completed' or 'failed'

    Args:
        analysis_id: ID of analysis (created by API)
        assessment_file: Path to assessment JSON file
        pdf_file: Path to PDF report file (optional)
        png_file: Path to PNG image file (optional)
        csv_file: Path to CSV data file (optional)
        output_prefix: Prefix for output files
        model: Model to use (gemini, ollama)
        important_programs: Programs marked as important by the user (Sigla
            values from the plot CSV)

    Returns:
        Dictionary with analysis info
    """
    try:
        logger.info(f"[Analysis {analysis_id}] Starting APOEMA Flow analysis with model={model}")
        # Update status to processing
        update_analysis_status(analysis_id, "processing")
        logger.info(f"[Analysis {analysis_id}] Status updated to 'processing'")

        # Create callback that saves results to database
        def on_task_complete(task_name: str, result: str):
            """Callback called when each task completes"""
            try:
                save_analysis_result(
                    analysis_id=analysis_id,
                    task_name=task_name,
                    result=result,
                )
                logger.info(f"[Analysis {analysis_id}] ✓ Saved result for task: {task_name}")
            except Exception as e:
                logger.error(f"[Analysis {analysis_id}] ✗ Failed to save result for {task_name}: {str(e)}")

        # Run the APOEMA Flow with callback
        # Note: run_apoema_flow is synchronous - Dramatiq workers already handle async execution
        logger.info(f"[Analysis {analysis_id}] Running CrewAI flow (max 15 minutes timeout)")
        analysis_result = run_apoema_flow(
            assessment_file=assessment_file,
            pdf_path=pdf_file,
            output_prefix=output_prefix,
            png_path=png_file,
            csv_path=csv_file,
            model=model,
            important_programs=important_programs,
            analysis_id=analysis_id,
            on_task_complete=on_task_complete,
        )
        logger.info(f"[Analysis {analysis_id}] CrewAI flow completed successfully")

        # Update analysis status to completed
        update_analysis_status(analysis_id, "completed")
        logger.info(f"[Analysis {analysis_id}] Analysis marked as completed")

        return {
            "analysis_id": analysis_id,
            "status": "completed",
            "message": "APOEMA Flow analysis completed successfully",
        }

    except Exception as e:
        logger.error(f"[Analysis {analysis_id}] ✗ Analysis failed with error: {str(e)}")
        logger.error(f"[Analysis {analysis_id}] Traceback:\n{traceback.format_exc()}")
        # Update analysis status to failed
        update_analysis_status(analysis_id, "failed")
        save_analysis_result(
            analysis_id,
            "run_analysis_flow_error",
            f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        raise e


@dramatiq.actor(
    max_retries=2,
    time_limit=7200000,  # 120 minutes (covers full 5-task flow even on a loaded/slow host)
    min_backoff=1000,   # 1 second
    max_backoff=30000,  # 30 seconds
    priority=0,         # Normal priority
)
def run_analysis_crew_with_tracking(
    analysis_id: int,
    assessment_file: str,
    pdf_file: str = None,
    output_prefix: str = None,
    png_file: str = None,
    csv_file: str = None,
    model: str = "gemini",
) -> dict:
    """
    Async task to run APOEMA Crew (traditional) analysis with database tracking.

    Args:
        analysis_id: ID of analysis (created by API)
        assessment_file: Path to assessment JSON file
        pdf_file: Path to PDF report file (optional)
        output_prefix: Prefix for output files
        png_file: Path to PNG image file (optional)
        csv_file: Path to CSV data file (optional)
        model: Model to use (gemini, ollama)

    Returns:
        Dictionary with analysis info
    """
    try:
        logger.info(f"[Analysis {analysis_id}] Starting APOEMA Crew analysis with model={model}")
        # Update status to processing
        update_analysis_status(analysis_id, "processing")
        logger.info(f"[Analysis {analysis_id}] Status updated to 'processing'")

        # Create callback that saves results to database
        def on_task_complete(task_name: str, result: str):
            """Callback called when each task completes"""
            try:
                save_analysis_result(
                    analysis_id=analysis_id,
                    task_name=task_name,
                    result=result,
                )
                logger.info(f"[Analysis {analysis_id}] ✓ Saved result for task: {task_name}")
            except Exception as e:
                logger.error(f"[Analysis {analysis_id}] ✗ Failed to save result for {task_name}: {str(e)}")

        # Run the APOEMA Crew (traditional)
        logger.info(f"[Analysis {analysis_id}] Running CrewAI crew (max 15 minutes timeout)")
        crew_result = run_apoema_pipeline(
            assessment_file=assessment_file,
            pdf_path=pdf_file,
            output_prefix=output_prefix,
            png_path=png_file,
            csv_path=csv_file,
            model=model,
        )
        logger.info(f"[Analysis {analysis_id}] CrewAI crew completed successfully")

        # Save final result
        save_analysis_result(
            analysis_id,
            "crew_completion",
            str(crew_result),
        )
        logger.info(f"[Analysis {analysis_id}] Final result saved")

        # Update analysis status to completed
        update_analysis_status(analysis_id, "completed")
        logger.info(f"[Analysis {analysis_id}] Analysis marked as completed")

        return {
            "analysis_id": analysis_id,
            "status": "completed",
            "message": "APOEMA Crew analysis completed successfully",
        }

    except Exception as e:
        logger.error(f"[Analysis {analysis_id}] ✗ Analysis failed with error: {str(e)}")
        logger.error(f"[Analysis {analysis_id}] Traceback:\n{traceback.format_exc()}")
        # Update analysis status to failed
        update_analysis_status(analysis_id, "failed")
        save_analysis_result(
            analysis_id,
            "run_analysis_crew_error",
            f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        raise e
