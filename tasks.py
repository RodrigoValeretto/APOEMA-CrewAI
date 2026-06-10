"""
Dramatiq tasks for async processing of APOEMA analysis

The workflow:
1. API creates 'analysis' record and sends Dramatiq task with analysis_id
2. Task receives analysis_id and creates callback function
3. Task runs CrewAI flow with callback
4. Each task completion in flow triggers callback → saves result to DB
5. Task updates final status to 'completed' or 'failed'
"""
import dramatiq
from dramatiq.brokers.rabbitmq import RabbitMQBroker
import os
from datetime import datetime
import asyncio
import traceback
from apoema_flow import run_apoema_flow
from apoema_agent import run_apoema_pipeline
from db_manager import (
    update_analysis_status,
    save_analysis_result,
)

# Configure RabbitMQ broker
rabbitmq_url = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672//")
broker = RabbitMQBroker(url=rabbitmq_url)
dramatiq.set_broker(broker)


@dramatiq.actor(store_results=True, max_retries=0)
def run_analysis_flow_with_tracking(
    analysis_id: int,
    assessment_file: str,
    pdf_file: str = None,
    png_file: str = None,
    csv_file: str = None,
    output_prefix: str = None,
    model: str = "gemini",
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

    Returns:
        Dictionary with analysis info
    """
    try:
        # Update status to processing
        update_analysis_status(analysis_id, "processing")

        # Create callback that saves results to database
        def on_task_complete(task_name: str, result: str):
            """Callback called when each task completes"""
            try:
                save_analysis_result(
                    analysis_id=analysis_id,
                    task_name=task_name,
                    result=result,
                )
                print(f"✓ Saved result for {task_name}")
            except Exception as e:
                print(f"✗ Failed to save result for {task_name}: {str(e)}")

        # Run the APOEMA Flow with callback
        result = asyncio.run(
            run_apoema_flow(
                assessment_file=assessment_file,
                pdf_path=pdf_file,
                output_prefix=output_prefix,
                png_path=png_file,
                csv_path=csv_file,
                model=model,
                analysis_id=analysis_id,
                on_task_complete=on_task_complete,
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
        update_analysis_status(analysis_id, "failed")
        save_analysis_result(
            analysis_id,
            "run_analysis_flow_error",
            f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        raise e


@dramatiq.actor(store_results=True, max_retries=0)
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
        # Update status to processing
        update_analysis_status(analysis_id, "processing")

        # Create callback that saves results to database
        def on_task_complete(task_name: str, result: str):
            """Callback called when each task completes"""
            try:
                save_analysis_result(
                    analysis_id=analysis_id,
                    task_name=task_name,
                    result=result,
                )
                print(f"✓ Saved result for {task_name}")
            except Exception as e:
                print(f"✗ Failed to save result for {task_name}: {str(e)}")

        # Run the APOEMA Crew (traditional)
        result = run_apoema_pipeline(
            assessment_file=assessment_file,
            pdf_path=pdf_file,
            output_prefix=output_prefix,
            png_path=png_file,
            csv_path=csv_file,
            model=model,
        )

        # Save final result
        save_analysis_result(
            analysis_id,
            "crew_completion",
            str(result),
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
        update_analysis_status(analysis_id, "failed")
        save_analysis_result(
            analysis_id,
            "run_analysis_crew_error",
            f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        raise e
