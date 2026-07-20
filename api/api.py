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
    FileExistsRequest,
    FileExistsResponse,
    HealthCheckResponse,
    ErrorResponse,
    DeleteResponse,
    ResultsResponse,
    TaskResult,
    ProgressInfo,
    FileDownloadRequest,
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
    InvalidURL,
    DatabaseError,
)
from .validators import (
    validate_analysis_request,
    determine_workflow_type,
    validate_model_choice,
)
from . import database, file_manager
from tasks import (
    enqueue_analysis_for_sequential_processing,
    index_file_for_rag,
)


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


# Helper function for resolving file sources
async def resolve_file_sources(request: AnalysisRequest) -> dict:
    """
    Resolve file sources by downloading from URLs if provided, otherwise using paths or file IDs.

    Args:
        request: AnalysisRequest with file specifications

    Returns:
        Dictionary with:
            - resolved file paths (assessment_file, pdf_path, png_path, csv_path)
            - file_ids: list of tuples (file_id, file_type) for downloaded files
    """
    resolved = {
        'assessment_file': request.assessment_file,
        'pdf_path': request.pdf_path,
        'png_path': request.png_path,
        'csv_path': request.csv_path,
        'file_ids': [],  # List of (file_id, file_type) tuples
    }

    # Download from URLs if provided and track file IDs
    if request.assessment_file_url:
        file_id, resolved['assessment_file'] = await file_manager.download_file_from_url(
            request.assessment_file_url,
            FileType.ASSESSMENT,
        )
        resolved['file_ids'].append((file_id, FileType.ASSESSMENT.value))

    if request.pdf_url:
        file_id, resolved['pdf_path'] = await file_manager.download_file_from_url(
            request.pdf_url,
            FileType.PDF,
        )
        resolved['file_ids'].append((file_id, FileType.PDF.value))

    if request.png_url:
        file_id, resolved['png_path'] = await file_manager.download_file_from_url(
            request.png_url,
            FileType.PNG,
        )
        resolved['file_ids'].append((file_id, FileType.PNG.value))

    if request.csv_url:
        file_id, resolved['csv_path'] = await file_manager.download_file_from_url(
            request.csv_url,
            FileType.CSV,
        )
        resolved['file_ids'].append((file_id, FileType.CSV.value))

    # Resolve file IDs to actual paths (for paths not set by URLs)
    if not resolved['assessment_file'] and request.assessment_file_id:
        resolved['assessment_file'] = file_manager.get_file_path(request.assessment_file_id)

    if not resolved['pdf_path'] and request.pdf_file_id:
        resolved['pdf_path'] = file_manager.get_file_path(request.pdf_file_id)

    if not resolved['png_path'] and request.png_file_id:
        resolved['png_path'] = file_manager.get_file_path(request.png_file_id)

    if not resolved['csv_path'] and request.csv_file_id:
        resolved['csv_path'] = file_manager.get_file_path(request.csv_file_id)

    return resolved


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
        # Validate input (including URLs)
        is_valid, error_msg = validate_analysis_request(
            assessment_file=request.assessment_file,
            assessment_file_id=request.assessment_file_id,
            assessment_file_url=request.assessment_file_url,
            pdf_path=request.pdf_path,
            pdf_file_id=request.pdf_file_id,
            pdf_url=request.pdf_url,
            png_path=request.png_path,
            png_file_id=request.png_file_id,
            png_url=request.png_url,
            csv_path=request.csv_path,
            csv_file_id=request.csv_file_id,
            csv_url=request.csv_url,
            model=request.model,
        )
        if not is_valid:
            raise InvalidAnalysisInput(error_msg)

        # Validate model
        validate_model_choice(request.model)

        # Resolve file sources (download from URLs, resolve IDs to paths)
        resolved_files = await resolve_file_sources(request)
        assessment_file = resolved_files['assessment_file']
        pdf_path = resolved_files['pdf_path']
        png_path = resolved_files['png_path']
        csv_path = resolved_files['csv_path']
        downloaded_file_ids = resolved_files['file_ids']

        # Determine workflow type (with resolved file paths)
        workflow_type = determine_workflow_type(
            pdf_path,
            png_path,
            csv_path,
        )

        # Create analysis record
        analysis_id = database.create_analysis(
            analysis_type=workflow_type,
            status=AnalysisStatus.PENDING.value,
        )

        # Collect all file IDs for mapping (both downloaded and passed as reference)
        all_file_mappings = list(downloaded_file_ids)  # Downloaded files

        # Add file IDs that were passed as references (not downloaded)
        if request.assessment_file_id and not any(ftype == FileType.ASSESSMENT.value for _, ftype in downloaded_file_ids):
            all_file_mappings.append((request.assessment_file_id, FileType.ASSESSMENT.value))

        if request.pdf_file_id and not any(ftype == FileType.PDF.value for _, ftype in downloaded_file_ids):
            all_file_mappings.append((request.pdf_file_id, FileType.PDF.value))

        if request.png_file_id and not any(ftype == FileType.PNG.value for _, ftype in downloaded_file_ids):
            all_file_mappings.append((request.png_file_id, FileType.PNG.value))

        if request.csv_file_id and not any(ftype == FileType.CSV.value for _, ftype in downloaded_file_ids):
            all_file_mappings.append((request.csv_file_id, FileType.CSV.value))

        # Create file mappings for all files (downloaded and referenced)
        for file_id, file_type in all_file_mappings:
            database.create_analysis_file_mapping(
                analysis_id=analysis_id,
                file_id=file_id,
                file_type=file_type,
            )

        # Submit Dramatiq task (via queue manager for sequential processing)
        enqueue_analysis_for_sequential_processing.send(
            analysis_id=analysis_id,
            assessment_file=assessment_file,
            pdf_file=pdf_path,
            png_file=png_path,
            csv_file=csv_path,
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

        # Delete analysis (cascade deletes results and mappings)
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

    Note:
        RAG indexing happens asynchronously in the background and does NOT block
        the upload response. The file is immediately available for analysis while
        indexing runs independently.
    """
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.ASSESSMENT,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        # Trigger asynchronous RAG indexing (non-blocking)
        # File is already saved and available, indexing happens in background
        index_file_for_rag.send(
            file_path=file_path,
            file_type=FileType.ASSESSMENT.value,
        )

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
    """
    Upload PDF report file

    Note:
        RAG indexing happens asynchronously in the background and does NOT block
        the upload response. The file is immediately available for analysis while
        indexing runs independently.
    """
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.PDF,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        # Trigger asynchronous RAG indexing (non-blocking)
        index_file_for_rag.send(
            file_path=file_path,
            file_type=FileType.PDF.value,
        )

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
    """
    Upload CSV data file

    Note:
        RAG indexing happens asynchronously in the background and does NOT block
        the upload response. The file is immediately available for analysis while
        indexing runs independently.
    """
    try:
        file_id, file_path = await file_manager.save_uploaded_file(
            file,
            FileType.CSV,
            analysis_id,
        )

        file_record = database.get_analysis_file(file_id)

        # Trigger asynchronous RAG indexing (non-blocking)
        index_file_for_rag.send(
            file_path=file_path,
            file_type=FileType.CSV.value,
        )

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
    "/api/files/download-from-url",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Files"],
)
async def download_file_from_url(
    request: FileDownloadRequest,
):
    """
    Download a file from a URL and save it to the system

    Args:
        request: Download request with URL, file type, and optional analysis ID

    Returns:
        File metadata with ID

    Raises:
        InvalidAnalysisInput: If URL is invalid
        URLFetchError: If download fails
    """
    try:
        file_id, file_path = await file_manager.download_file_from_url(
            request.url,
            request.file_type,
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
    "/api/files/exists",
    response_model=FileExistsResponse,
    tags=["Files"],
)
async def check_file_exists(request: FileExistsRequest):
    """
    Check if a file from a given URL already exists in the system

    Args:
        request: FileExistsRequest with URL to check

    Returns:
        FileExistsResponse with existence status and file details if it exists

    Raises:
        HTTPException: 400 if URL is invalid, 500 if database error occurs
    """
    try:
        # Validate URL format
        from .validators import validate_url
        validate_url(request.url)

        # Check if file exists
        file_record = file_manager.get_file_by_url(request.url)

        if file_record:
            return FileExistsResponse(
                exists=True,
                file_id=file_record["id"],
                filename=file_record["file_name"],
                created_at=file_record["created_at"],
            )
        else:
            return FileExistsResponse(
                exists=False,
                file_id=None,
                filename=None,
                created_at=None,
            )

    except InvalidURL as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL: {str(e)}",
        )
    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
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
