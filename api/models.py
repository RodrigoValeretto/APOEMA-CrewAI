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
    assessment_file_url: Optional[str] = Field(
        None,
        description="URL to assessment JSON file (alternative to assessment_file or assessment_file_id)",
        examples=["https://example.com/assessment.json"],
    )
    pdf_url: Optional[str] = Field(
        None,
        description="URL to PDF report file (alternative to pdf_path or pdf_file_id)",
        examples=["https://example.com/report.pdf"],
    )
    png_url: Optional[str] = Field(
        None,
        description="URL to PNG plot image (alternative to png_path or png_file_id)",
        examples=["https://example.com/plot.png"],
    )
    csv_url: Optional[str] = Field(
        None,
        description="URL to CSV data file (alternative to csv_path or csv_file_id)",
        examples=["https://example.com/data.csv"],
    )
    model: str = Field(
        default=ModelType.OLLAMA.value,
        description="LLM model to use",
        pattern="^(gemini|ollama)$",
    )
    important_programs: Optional[List[str]] = Field(
        None,
        description=(
            "Program identifiers (Sigla values from the plot CSV) marked as "
            "important by the user; the plot highlights them and the AI insights "
            "must consider them"
        ),
        examples=[["UFPA-A-5-CC", "UFBA-A-5-CC"]],
    )
    informativo_id: Optional[int] = Field(
        None,
        description=(
            "ID of an informativo (CAPES area corpus). The informativo's converted "
            "ficha is used as the assessment file and its converted anexos/adendos "
            "are attached as extra Knowledge sources (retrieval). Alternative to "
            "assessment_file / assessment_file_id / assessment_file_url."
        ),
        examples=[1],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "assessment_file": "/app/input/cc_assessment_data.json",
                "pdf_path": "/app/input/cc_report.pdf",
                "model": "gemini",
            }
        }
    }

    @validator("assessment_file", "pdf_path", "png_path", "csv_path", "assessment_file_url", "pdf_url", "png_url", "csv_url", pre=True)
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

    model_config = {
        "json_schema_extra": {
            "example": {
                "file_type": "assessment",
            }
        }
    }


class FileDownloadRequest(BaseModel):
    """Request model for downloading files from URL"""

    url: str = Field(
        ...,
        description="URL of the file to download",
        examples=["https://example.com/image.png"],
    )
    file_type: FileType = Field(
        ..., description="Type of file being downloaded"
    )
    analysis_id: Optional[int] = Field(
        None,
        description="Optional analysis ID to associate downloaded file with",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://example.com/plot.png",
                "file_type": "png",
            }
        }
    }


# Response Models
class AnalysisResponse(BaseModel):
    """Response model for analysis creation"""

    id: int = Field(..., description="Unique analysis ID")
    type: str = Field(..., description="Analysis type (pdf, png_csv, basic)")
    status: str = Field(..., description="Current analysis status")
    created_at: datetime = Field(..., description="Creation timestamp")
    important_programs: Optional[List[str]] = Field(
        None,
        description="Program identifiers marked as important by the user",
    )
    informativo_id: Optional[int] = Field(
        None,
        description="Informativo (CAPES area corpus) that sourced this analysis, if any",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 42,
                "type": "pdf",
                "status": "pending",
                "created_at": "2024-06-09T12:00:00Z",
            }
        }
    }


class TaskResult(BaseModel):
    """Model for task result"""

    id: int = Field(..., description="Result ID")
    task_name: str = Field(..., description="Name of the task that produced this result")
    result: str = Field(..., description="Result content")
    created_at: datetime = Field(..., description="Creation timestamp")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 101,
                "task_name": "task_1_data_analysis",
                "result": "Critérios CAPES extraídos com sucesso...",
                "created_at": "2024-06-09T12:05:00Z",
            }
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

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_tasks_expected": 6,
                "completed_tasks": 3,
                "percentage": 50.0,
            }
        }
    }


class AnalysisDetailResponse(BaseModel):
    """Detailed response model for analysis"""

    id: int
    type: str
    status: str
    created_at: datetime
    updated_at: datetime
    important_programs: Optional[List[str]] = Field(
        None,
        description="Program identifiers marked as important by the user",
    )
    informativo_id: Optional[int] = Field(
        None,
        description="Informativo (CAPES area corpus) that sourced this analysis, if any",
    )
    results: List[TaskResult] = Field(default_factory=list)
    progress: ProgressInfo

    model_config = {
        "json_schema_extra": {
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
    important_programs: Optional[List[str]] = Field(
        None,
        description="Program identifiers marked as important by the user",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 42,
                "type": "pdf",
                "status": "completed",
                "created_at": "2024-06-09T12:00:00Z",
                "results_count": 6,
            }
        }
    }


class AnalysisListResponse(BaseModel):
    """Response model for paginated analysis list"""

    total: int = Field(..., description="Total number of analyses")
    skip: int = Field(..., description="Number of items skipped")
    limit: int = Field(..., description="Number of items returned")
    items: List[AnalysisListItem] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
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
    }


class FileUploadResponse(BaseModel):
    """Response model for file upload"""

    id: int = Field(..., description="File ID")
    filename: str = Field(..., description="Original filename")
    file_type: str = Field(..., description="Type of file")
    size: int = Field(..., description="File size in bytes")
    created_at: datetime = Field(..., description="Upload timestamp")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "filename": "report.pdf",
                "file_type": "pdf",
                "size": 12180513,
                "created_at": "2024-06-09T12:00:00Z",
            }
        }
    }


class FileExistsRequest(BaseModel):
    """Request model for checking if a file exists"""

    url: str = Field(..., description="URL to check for existing file")

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://example.com/document.pdf",
            }
        }
    }


class FileExistsResponse(BaseModel):
    """Response model for file existence check"""

    exists: bool = Field(..., description="Whether the file already exists")
    file_id: Optional[int] = Field(None, description="File ID if it exists")
    filename: Optional[str] = Field(None, description="Filename if it exists")
    created_at: Optional[datetime] = Field(None, description="Upload timestamp if it exists")

    model_config = {
        "json_schema_extra": {
            "example": {
                "exists": True,
                "file_id": 1,
                "filename": "report.pdf",
                "created_at": "2024-06-09T12:00:00Z",
            }
        }
    }


class HealthCheckResponse(BaseModel):
    """Health check response"""

    status: str = Field(..., description="Overall status")
    timestamp: datetime = Field(..., description="Check timestamp")
    services: dict = Field(default_factory=dict, description="Service status details")

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "ok",
                "timestamp": "2024-06-09T12:00:00Z",
                "services": {
                    "database": "ok",
                    "rabbitmq": "ok",
                },
            }
        }
    }


class ErrorResponse(BaseModel):
    """Error response model"""

    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    timestamp: datetime = Field(..., description="Error timestamp")

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": "ANALYSIS_NOT_FOUND",
                "message": "Analysis with ID 999 not found",
                "timestamp": "2024-06-09T12:00:00Z",
            }
        }
    }


class DeleteResponse(BaseModel):
    """Response for delete operations"""

    message: str = Field(..., description="Success message")
    id: int = Field(..., description="ID of deleted item")

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Analysis deleted successfully",
                "id": 42,
            }
        }
    }


class ResultsResponse(BaseModel):
    """Response model for analysis results"""

    analysis_id: int = Field(..., description="Analysis ID")
    results: List[TaskResult] = Field(default_factory=list)

    model_config = {
        "json_schema_extra": {
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
    }


# ---------------------------------------------------------------------------
# Informativos (CAPES area corpus) + document conversion
# ---------------------------------------------------------------------------
class InformativoCreate(BaseModel):
    """Request model for creating an informativo"""

    nome: str = Field(
        ...,
        min_length=3,
        description="Human name of the CAPES area (e.g. 'Ciência da Computação')",
        examples=["Ciência da Computação"],
    )
    quadrienio: Optional[str] = Field(
        None,
        description="CAPES quadrennium label",
        examples=["2025-2028"],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "nome": "Ciência da Computação",
                "quadrienio": "2025-2028",
            }
        }
    }


class InformativoResponse(BaseModel):
    """Response model for an informativo"""

    id: int
    nome: str
    slug: str
    quadrienio: Optional[str] = None
    created_at: datetime
    total_documents: int = Field(default=0)
    completed_documents: int = Field(default=0)

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 1,
                "nome": "Ciência da Computação",
                "slug": "ciencia_da_computacao",
                "quadrienio": "2025-2028",
                "created_at": "2026-09-04T12:00:00Z",
                "total_documents": 3,
                "completed_documents": 2,
            }
        }
    }


class InformativoListResponse(BaseModel):
    """Response model for informativo listing"""

    total: int
    items: List[InformativoResponse]


class InformativoDocumentResponse(BaseModel):
    """Response model for an informativo document + its conversion state"""

    id: int
    informativo_id: int
    kind: str  # ficha | anexo | adendo
    status: str  # pending | processing | completed | failed
    error: Optional[str] = None
    original_file_id: Optional[int] = None
    original_file_name: Optional[str] = None
    original_file_size: Optional[int] = None
    converted_file_id: Optional[int] = None
    converted_file_name: Optional[str] = None
    converted_file_size: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 7,
                "informativo_id": 1,
                "kind": "ficha",
                "status": "completed",
                "original_file_name": "COMPUTACAO_FICHA_2025_2028.pdf",
                "converted_file_name": "doc_7.json",
                "converted_file_size": 41220,
            }
        }
    }


class InformativoDocumentListResponse(BaseModel):
    """Response model for the documents of an informativo"""

    informativo_id: int
    items: List[InformativoDocumentResponse]
