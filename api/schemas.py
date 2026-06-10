"""
Advanced response schemas and data models
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class BaseResponse(BaseModel):
    """Base response model for all API responses"""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Response message")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of the response",
    )

    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "timestamp": "2024-06-09T12:00:00Z",
            }
        }


class PaginatedResponse(BaseModel):
    """Generic paginated response"""

    total: int = Field(..., description="Total number of items")
    skip: int = Field(..., description="Number of items skipped")
    limit: int = Field(..., description="Number of items per page")
    items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of items on current page",
    )
    has_more: bool = Field(
        ...,
        description="Whether there are more items available",
    )

    @property
    def current_page(self) -> int:
        """Calculate current page number"""
        return (self.skip // self.limit) + 1 if self.limit > 0 else 1

    @property
    def total_pages(self) -> int:
        """Calculate total pages"""
        return (self.total + self.limit - 1) // self.limit if self.limit > 0 else 1


class ProgressStatus(BaseModel):
    """Task progress status"""

    task_index: int = Field(
        ...,
        description="Current task index (1-based)",
        ge=1,
    )
    task_name: str = Field(..., description="Name of current task")
    status: str = Field(
        ...,
        description="Status of current task (running, completed, failed)",
    )
    percentage: float = Field(
        ...,
        description="Overall progress percentage",
        ge=0,
        le=100,
    )
    elapsed_time: int = Field(
        ...,
        description="Elapsed time in seconds",
        ge=0,
    )
    estimated_remaining_time: Optional[int] = Field(
        None,
        description="Estimated remaining time in seconds",
    )


class DetailedAnalysisResponse(BaseModel):
    """Detailed analysis with all metadata"""

    id: int
    type: str
    status: str
    created_at: datetime
    updated_at: datetime
    results_count: int
    expected_results: int
    progress_percentage: float
    results: List[Dict[str, Any]]
    files: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = Field(None, description="Error message if failed")

    class Config:
        schema_extra = {
            "example": {
                "id": 42,
                "type": "pdf",
                "status": "completed",
                "created_at": "2024-06-09T12:00:00Z",
                "updated_at": "2024-06-09T12:35:00Z",
                "results_count": 6,
                "expected_results": 6,
                "progress_percentage": 100.0,
                "results": [
                    {
                        "id": 101,
                        "task_name": "task_1_data_analysis",
                        "result": "...",
                        "created_at": "2024-06-09T12:05:00Z",
                    }
                ],
                "files": [],
                "error": None,
            }
        }


class StreamingEventMessage(BaseModel):
    """Message for Server-Sent Events (SSE) streaming"""

    event_type: str = Field(
        ...,
        description="Type of event (status_change, result_added, error, complete)",
    )
    data: Dict[str, Any] = Field(..., description="Event data")
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Event timestamp",
    )

    class Config:
        schema_extra = {
            "example": {
                "event_type": "result_added",
                "data": {
                    "task_name": "task_1_data_analysis",
                    "result": "...",
                },
                "timestamp": "2024-06-09T12:05:00Z",
            }
        }


class BulkAnalysisRequest(BaseModel):
    """Request for bulk analysis of multiple files"""

    files: List[Dict[str, Any]] = Field(
        ...,
        description="List of files to analyze",
        min_items=1,
    )
    model: str = Field(
        default="gemini",
        description="LLM model to use",
    )
    parallel: bool = Field(
        default=False,
        description="Whether to process files in parallel",
    )


class BulkAnalysisResponse(BaseModel):
    """Response for bulk analysis"""

    batch_id: str = Field(..., description="Unique batch ID")
    total_files: int = Field(..., description="Total files in batch")
    analysis_ids: List[int] = Field(
        ...,
        description="List of analysis IDs created",
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Batch creation timestamp",
    )

    class Config:
        schema_extra = {
            "example": {
                "batch_id": "batch_12345",
                "total_files": 3,
                "analysis_ids": [42, 43, 44],
                "created_at": "2024-06-09T12:00:00Z",
            }
        }


class BulkAnalysisStatusResponse(BaseModel):
    """Response for bulk analysis status"""

    batch_id: str = Field(..., description="Batch ID")
    total_files: int = Field(..., description="Total files")
    completed: int = Field(..., description="Completed analyses")
    failed: int = Field(..., description="Failed analyses")
    in_progress: int = Field(..., description="In progress analyses")
    percentage_complete: float = Field(
        ...,
        description="Overall completion percentage",
    )
    analyses: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Status of each analysis",
    )
