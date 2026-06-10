"""
APOEMA FastAPI Application with all endpoints
"""
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Query,
    File,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from datetime import datetime
from typing import Optional
import os

from config import get_config
from db_manager import (
    create_analysis,
    get_analysis,
    update_analysis_status,
    save_analysis_result,
    get_analysis_results,
    delete_analysis,
)
from .models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisDetailResponse,
    AnalysisListResponse,
    FileUploadResponse,
    HealthCheckResponse,
    ErrorResponse,
    DeleteResponse,
    ResultsResponse,
    TaskResult,
    ProgressInfo,
)
from .constants import (
    AnalysisType,
    AnalysisStatus,
    FileType,
    ErrorCode,
    EXPECTED_TASKS,
)
from .exceptions import (
    ApoemaException,
    AnalysisNotFound,
    InvalidAnalysisInput,
)
from .validators import (
    validate_analysis_request,
    determine_workflow_type,
    validate_model_choice,
)
from . import database, file_manager
from tasks import run_analysis_flow_with_tracking, run_analysis_crew_with_tracking


config = get_config()

# Create FastAPI app
app = FastAPI(
    title="APOEMA API",
    description="API for APOEMA - AI-powered assessment analysis",
    version="1.0.0",
)


# Exception handlers
@app.exception_handler(ApoemaException)
async def apoema_exception_handler(request, exc: ApoemaException):
    """Handle APOEMA custom exceptions"""
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": exc.error_code.value,
            "message": exc.detail,
            "timestamp": datetime.now().isoformat(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Handle HTTP exceptions"""
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "error": ErrorCode.INTERNAL_SERVER_ERROR.value,
            "message": str(exc.detail),
            "timestamp": datetime.now().isoformat(),
        },
    )


# Health check endpoint
@app.get(
    "/health",
    response_model=HealthCheckResponse,
    tags=["Health"],
)
async def health_check():
    """
    Health check endpoint

    Returns:
        Health status and service availability
    """
    services = {"api": "ok"}

    # Check database
    try:
        _ = database.get_connection()
        services["database"] = "ok"
    except Exception as e:
        services["database"] = f"error: {str(e)}"

    # Determine overall status
    overall_status = "ok" if all(v == "ok" for v in services.values()) else "degraded"

    return HealthCheckResponse(
        status=overall_status,
        timestamp=datetime.now(),
        services=services,
    )


# Analysis endpoints
@app.post(
    "/api/analysis",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Analysis"],
)
async def create_analysis_endpoint(request: AnalysisRequest):
    """
    Submit a new analysis

    Args:
        request: Analysis request with file paths and model

    Returns:
        Analysis metadata with ID and status

    Raises:
        InvalidAnalysisInput: If input is invalid
    """
    try:
        # Validate input
        is_valid, error_msg = validate_analysis_request(
            assessment_file=request.assessment_file,
            assessment_file_id=request.assessment_file_id,
            pdf_path=request.pdf_path,
            pdf_file_id=request.pdf_file_id,
            png_path=request.png_path,
            png_file_id=request.png_file_id,
            csv_path=request.csv_path,
            csv_file_id=request.csv_file_id,
            model=request.model,
        )
        if not is_valid:
            raise InvalidAnalysisInput(error_msg)

        # Validate model
        validate_model_choice(request.model)

        # Determine workflow type
        workflow_type = determine_workflow_type(
            request.pdf_path or (request.pdf_file_id and f"file_{request.pdf_file_id}"),
            request.png_path or (request.png_file_id and f"file_{request.png_file_id}"),
            request.csv_path or (request.csv_file_id and f"file_{request.csv_file_id}"),
        )

        # Create analysis record
        analysis_id = database.create_analysis(
            analysis_type=workflow_type,
            status=AnalysisStatus.PENDING.value,
        )

        # Get file paths (resolve file IDs if needed)
        assessment_file = request.assessment_file
        if not assessment_file and request.assessment_file_id:
            assessment_file = file_manager.get_file_path(request.assessment_file_id)

        pdf_path = request.pdf_path
        if not pdf_path and request.pdf_file_id:
            pdf_path = file_manager.get_file_path(request.pdf_file_id)

        png_path = request.png_path
        if not png_path and request.png_file_id:
            png_path = file_manager.get_file_path(request.png_file_id)

        csv_path = request.csv_path
        if not csv_path and request.csv_file_id:
            csv_path = file_manager.get_file_path(request.csv_file_id)

        # Submit Dramatiq task
        run_analysis_flow_with_tracking.send(
            analysis_id=analysis_id,
            assessment_file=assessment_file,
            pdf_path=pdf_path,
            png_path=png_path,
            csv_path=csv_path,
            output_prefix=f"analysis_{analysis_id}",
            model=request.model,
        )

        return AnalysisResponse(
            id=analysis_id,
            type=workflow_type,
            status=AnalysisStatus.PENDING.value,
            created_at=datetime.now(),
        )

    except ApoemaException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get(
    "/api/analysis/{analysis_id}",
    response_model=AnalysisDetailResponse,
    tags=["Analysis"],
)
async def get_analysis_endpoint(analysis_id: int):
    """
    Get detailed information about an analysis

    Args:
        analysis_id: ID of analysis

    Returns:
        Complete analysis details with all results

    Raises:
        AnalysisNotFound: If analysis doesn't exist
    """
    try:
        # Get analysis
        analysis = database.get_analysis(analysis_id)

        # Get results
        results = database.get_analysis_results(analysis_id)
        task_results = [
            TaskResult(
                id=r["id"],
                task_name=r["task_name"],
                result=r["result"],
                created_at=r["created_at"],
            )
            for r in results
        ]

        # Calculate progress
        expected_tasks = EXPECTED_TASKS.get(analysis["type"], 0)
        completed_tasks = len(results)
        percentage = (completed_tasks / expected_tasks * 100) if expected_tasks > 0 else 0

        progress = ProgressInfo(
            total_tasks_expected=expected_tasks,
            completed_tasks=completed_tasks,
            percentage=round(percentage, 2),
        )

        return AnalysisDetailResponse(
            id=analysis["id"],
            type=analysis["type"],
            status=analysis["status"],
            created_at=analysis["created_at"],
            updated_at=analysis["updated_at"],
            results=task_results,
            progress=progress,
        )

    except AnalysisNotFound:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get(
    "/api/analysis",
    response_model=AnalysisListResponse,
    tags=["Analysis"],
)
async def list_analyses_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """
    List analyses with pagination and filters

    Args:
        skip: Number of records to skip
        limit: Maximum number of records
        type: Filter by analysis type (pdf, png_csv, basic)
        status: Filter by status (pending, processing, completed, failed)

    Returns:
        Paginated list of analyses
    """
    try:
        total, analyses = database.get_all_analyses(
            skip=skip,
            limit=limit,
            analysis_type=type,
            status=status,
        )

        items = [
            {
                "id": a["id"],
                "type": a["type"],
                "status": a["status"],
                "created_at": a["created_at"],
                "results_count": a.get("results_count", 0),
            }
            for a in analyses
        ]

        return AnalysisListResponse(
            total=total,
            skip=skip,
            limit=limit,
            items=items,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.delete(
    "/api/analysis/{analysis_id}",
    response_model=DeleteResponse,
    tags=["Analysis"],
)
async def delete_analysis_endpoint(analysis_id: int):
    """
    Delete an analysis and its results

    Args:
        analysis_id: ID of analysis to delete

    Returns:
        Confirmation message
    """
    try:
        # Verify analysis exists
        _ = database.get_analysis(analysis_id)

        # Clean up files
        file_manager.cleanup_analysis_files(analysis_id)

        # Delete analysis (cascade deletes results)
        database.delete_analysis(analysis_id)

        return DeleteResponse(
            message="Analysis deleted successfully",
            id=analysis_id,
        )

    except AnalysisNotFound:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.get(
    "/api/analysis/{analysis_id}/results",
    response_model=ResultsResponse,
    tags=["Analysis"],
)
async def get_analysis_results_endpoint(
    analysis_id: int,
    task_name: Optional[str] = Query(None),
):
    """
    Get all results for an analysis

    Args:
        analysis_id: ID of analysis
        task_name: Optional filter by specific task

    Returns:
        List of task results
    """
    try:
        # Verify analysis exists
        _ = database.get_analysis(analysis_id)

        # Get results
        results = database.get_analysis_results(analysis_id, task_name)
        task_results = [
            TaskResult(
                id=r["id"],
                task_name=r["task_name"],
                result=r["result"],
                created_at=r["created_at"],
            )
            for r in results
        ]

        return ResultsResponse(
            analysis_id=analysis_id,
            results=task_results,
        )

    except AnalysisNotFound:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# File upload endpoints
@app.post(
    "/api/files/assessment",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Files"],
)
async def upload_assessment_file(
    file: UploadFile = File(...),
    analysis_id: Optional[int] = Query(None),
):
    """
    Upload assessment JSON file

    Args:
        file: JSON file to upload
        analysis_id: Optional associated analysis ID

    Returns:
        File metadata with ID
    """
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.ASSESSMENT,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        return FileUploadResponse(
            id=file_record["id"],
            filename=file_record["file_name"],
            file_type=file_record["file_type"],
            size=file_record["file_size"],
            created_at=file_record["created_at"],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post(
    "/api/files/pdf",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Files"],
)
async def upload_pdf_file(
    file: UploadFile = File(...),
    analysis_id: Optional[int] = Query(None),
):
    """Upload PDF report file"""
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.PDF,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        return FileUploadResponse(
            id=file_record["id"],
            filename=file_record["file_name"],
            file_type=file_record["file_type"],
            size=file_record["file_size"],
            created_at=file_record["created_at"],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post(
    "/api/files/png",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Files"],
)
async def upload_png_file(
    file: UploadFile = File(...),
    analysis_id: Optional[int] = Query(None),
):
    """Upload PNG plot image"""
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.PNG,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        return FileUploadResponse(
            id=file_record["id"],
            filename=file_record["file_name"],
            file_type=file_record["file_type"],
            size=file_record["file_size"],
            created_at=file_record["created_at"],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.post(
    "/api/files/csv",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Files"],
)
async def upload_csv_file(
    file: UploadFile = File(...),
    analysis_id: Optional[int] = Query(None),
):
    """Upload CSV data file"""
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.CSV,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        return FileUploadResponse(
            id=file_record["id"],
            filename=file_record["file_name"],
            file_type=file_record["file_type"],
            size=file_record["file_size"],
            created_at=file_record["created_at"],
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.delete(
    "/api/files/{file_id}",
    response_model=DeleteResponse,
    tags=["Files"],
)
async def delete_file_endpoint(file_id: int):
    """
    Delete an uploaded file

    Args:
        file_id: ID of file to delete

    Returns:
        Confirmation message
    """
    try:
        file_manager.delete_file(file_id)

        return DeleteResponse(
            message="File deleted successfully",
            id=file_id,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# Root redirect
@app.get("/", tags=["Root"])
async def root():
    """Redirect to API documentation"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


# Exception handlers setup happens automatically when app is defined
