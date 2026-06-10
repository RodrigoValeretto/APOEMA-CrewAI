"""
Pydantic models for request and response validation
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, validator
from .constants import ModelType, AnalysisType, AnalysisStatus, FileType


# Request Models
class AnalysisRequest(BaseModel):
    """Request model for creating a new analysis"""

    assessment_file: Optional[str] = Field(
        None,
        description="Path to assessment JSON file",
        examples=["/app/input/cc_assessment_data.json"],
    )
    assessment_file_id: Optional[int] = Field(
        None,
        description="ID of uploaded assessment file (alternative to assessment_file)",
    )
    pdf_path: Optional[str] = Field(
        None,
        description="Path to PDF report file",
        examples=["/app/input/cc_report.pdf"],
    )
    pdf_file_id: Optional[int] = Field(
        None,
        description="ID of uploaded PDF file (alternative to pdf_path)",
    )
    png_path: Optional[str] = Field(
        None,
        description="Path to PNG plot image",
        examples=["/app/input/plot.png"],
    )
    png_file_id: Optional[int] = Field(
        None,
        description="ID of uploaded PNG file (alternative to png_path)",
    )
    csv_path: Optional[str] = Field(
        None,
        description="Path to CSV data file",
        examples=["/app/input/data.csv"],
    )
    csv_file_id: Optional[int] = Field(
        None,
        description="ID of uploaded CSV file (alternative to csv_path)",
    )
    model: str = Field(
        default=ModelType.GEMINI.value,
        description="LLM model to use",
        regex="^(gemini|ollama)$",
    )

    class Config:
        schema_extra = {
            "example": {
                "assessment_file": "/app/input/cc_assessment_data.json",
                "pdf_path": "/app/input/cc_report.pdf",
                "model": "gemini",
            }
        }

    @validator("assessment_file", "pdf_path", "png_path", "csv_path", pre=True)
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v


class FileUploadRequest(BaseModel):
    """Request model for file uploads"""

    file_type: FileType = Field(
        ..., description="Type of file being uploaded"
    )
    analysis_id: Optional[int] = Field(
        None,
        description="Optional analysis ID to associate file with",
    )

    class Config:
        schema_extra = {
            "example": {
                "file_type": "assessment",
            }
        }


# Response Models
class AnalysisResponse(BaseModel):
    """Response model for analysis creation"""

    id: int = Field(..., description="Unique analysis ID")
    type: str = Field(..., description="Analysis type (pdf, png_csv, basic)")
    status: str = Field(..., description="Current analysis status")
    created_at: datetime = Field(..., description="Creation timestamp")

    class Config:
        schema_extra = {
            "example": {
                "id": 42,
                "type": "pdf",
                "status": "pending",
                "created_at": "2024-06-09T12:00:00Z",
            }
        }


class TaskResult(BaseModel):
    """Model for task result"""

    id: int = Field(..., description="Result ID")
    task_name: str = Field(..., description="Name of the task that produced this result")
    result: str = Field(..., description="Result content")
    created_at: datetime = Field(..., description="Creation timestamp")

    class Config:
        schema_extra = {
            "example": {
                "id": 101,
                "task_name": "task_1_data_analysis",
                "result": "Critérios CAPES extraídos com sucesso...",
                "created_at": "2024-06-09T12:05:00Z",
            }
        }


class ProgressInfo(BaseModel):
    """Progress information for analysis"""

    total_tasks_expected: int = Field(
        ..., description="Total number of tasks expected to run"
    )
    completed_tasks: int = Field(
        ..., description="Number of tasks completed"
    )
    percentage: float = Field(
        ..., ge=0, le=100, description="Percentage of completion (0-100)"
    )

    class Config:
        schema_extra = {
            "example": {
                "total_tasks_expected": 6,
                "completed_tasks": 3,
                "percentage": 50.0,
            }
        }


class AnalysisDetailResponse(BaseModel):
    """Detailed response model for analysis"""

    id: int
    type: str
    status: str
    created_at: datetime
    updated_at: datetime
    results: List[TaskResult] = Field(default_factory=list)
    progress: ProgressInfo

    class Config:
        schema_extra = {
            "example": {
                "id": 42,
                "type": "pdf",
                "status": "processing",
                "created_at": "2024-06-09T12:00:00Z",
                "updated_at": "2024-06-09T12:05:00Z",
                "results": [
                    {
                        "id": 101,
                        "task_name": "task_1_data_analysis",
                        "result": "...",
                        "created_at": "2024-06-09T12:05:00Z",
                    }
                ],
                "progress": {
                    "total_tasks_expected": 6,
                    "completed_tasks": 1,
                    "percentage": 16.67,
                },
            }
        }


class AnalysisListItem(BaseModel):
    """Model for analysis item in list"""

    id: int = Field(..., description="Analysis ID")
    type: str = Field(..., description="Analysis type")
    status: str = Field(..., description="Analysis status")
    created_at: datetime = Field(..., description="Creation timestamp")
    results_count: int = Field(
        default=0, description="Number of results/tasks completed"
    )

    class Config:
        schema_extra = {
            "example": {
                "id": 42,
                "type": "pdf",
                "status": "completed",
                "created_at": "2024-06-09T12:00:00Z",
                "results_count": 6,
            }
        }


class AnalysisListResponse(BaseModel):
    """Response model for paginated analysis list"""

    total: int = Field(..., description="Total number of analyses")
    skip: int = Field(..., description="Number of items skipped")
    limit: int = Field(..., description="Number of items returned")
    items: List[AnalysisListItem] = Field(default_factory=list)

    class Config:
        schema_extra = {
            "example": {
                "total": 150,
                "skip": 0,
                "limit": 10,
                "items": [
                    {
                        "id": 42,
                        "type": "pdf",
                        "status": "completed",
                        "created_at": "2024-06-09T12:00:00Z",
                        "results_count": 6,
                    }
                ],
            }
        }


class FileUploadResponse(BaseModel):
    """Response model for file upload"""

    id: int = Field(..., description="File ID")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="Type of file")
    size: int = Field(..., description="File size in bytes")
    created_at: datetime = Field(..., description="Upload timestamp")

    class Config:
        schema_extra = {
            "example": {
                "id": 1,
                "filename": "report.pdf",
                "file_type": "pdf",
                "size": 12180513,
                "created_at": "2024-06-09T12:00:00Z",
            }
        }


class HealthCheckResponse(BaseModel):
    """Health check response"""

    status: str = Field(..., description="Overall status")
    timestamp: datetime = Field(..., description="Check timestamp")
    services: dict = Field(default_factory=dict, description="Service status details")

    class Config:
        schema_extra = {
            "example": {
                "status": "ok",
                "timestamp": "2024-06-09T12:00:00Z",
                "services": {
                    "database": "ok",
                    "rabbitmq": "ok",
                },
            }
        }


class ErrorResponse(BaseModel):
    """Error response model"""

    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    timestamp: datetime = Field(..., description="Error timestamp")

    class Config:
        schema_extra = {
            "example": {
                "error": "ANALYSIS_NOT_FOUND",
                "message": "Analysis with ID 999 not found",
                "timestamp": "2024-06-09T12:00:00Z",
            }
        }


class DeleteResponse(BaseModel):
    """Response for delete operations"""

    message: str = Field(..., description="Success message")
    id: int = Field(..., description="ID of deleted item")

    class Config:
        schema_extra = {
            "example": {
                "message": "Analysis deleted successfully",
                "id": 42,
            }
        }


class ResultsResponse(BaseModel):
    """Response model for analysis results"""

    analysis_id: int = Field(..., description="Analysis ID")
    results: List[TaskResult] = Field(default_factory=list)

    class Config:
        schema_extra = {
            "example": {
                "analysis_id": 42,
                "results": [
                    {
                        "id": 101,
                        "task_name": "task_1_data_analysis",
                        "result": "...",
                        "created_at": "2024-06-09T12:05:00Z",
                    }
                ],
            }
        }
