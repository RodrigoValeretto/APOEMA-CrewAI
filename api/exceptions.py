"""
Custom exceptions for APOEMA API
"""
from fastapi import HTTPException, status
from .constants import ErrorCode


class ApoemaException(Exception):
    """Base exception for all APOEMA errors"""

    def __init__(
        self,
        detail: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ):
        self.detail = detail
        self.error_code = error_code
        self.status_code = status_code
        super().__init__(self.detail)

    def to_http_exception(self) -> HTTPException:
        """Convert to FastAPI HTTPException"""
        return HTTPException(
            status_code=self.status_code,
            detail={
                "error": self.error_code.value,
                "message": self.detail,
            },
        )


class AnalysisNotFound(ApoemaException):
    """Analysis with given ID not found"""

    def __init__(self, analysis_id: int):
        super().__init__(
            detail=f"Analysis with ID {analysis_id} not found",
            error_code=ErrorCode.ANALYSIS_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class FileNotFound(ApoemaException):
    """File not found"""

    def __init__(self, file_path: str):
        super().__init__(
            detail=f"File not found: {file_path}",
            error_code=ErrorCode.FILE_NOT_FOUND,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidAnalysisInput(ApoemaException):
    """Invalid input for analysis request"""

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_code=ErrorCode.INVALID_INPUT,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class DatabaseError(ApoemaException):
    """Database operation failed"""

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_code=ErrorCode.DATABASE_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class FileUploadError(ApoemaException):
    """File upload failed"""

    def __init__(self, detail: str):
        super().__init__(
            detail=detail,
            error_code=ErrorCode.FILE_UPLOAD_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class InvalidFileType(ApoemaException):
    """Invalid file type"""

    def __init__(self, file_type: str, allowed_types: list):
        detail = f"Invalid file type: {file_type}. Allowed types: {', '.join(allowed_types)}"
        super().__init__(
            detail=detail,
            error_code=ErrorCode.INVALID_FILE_TYPE,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class FileTooLarge(ApoemaException):
    """File size exceeds maximum allowed"""

    def __init__(self, file_size: int, max_size: int):
        detail = f"File size ({file_size} bytes) exceeds maximum allowed ({max_size} bytes)"
        super().__init__(
            detail=detail,
            error_code=ErrorCode.FILE_TOO_LARGE,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class UnsupportedModel(ApoemaException):
    """Model is not supported"""

    def __init__(self, model: str, supported_models: list):
        detail = f"Model '{model}' is not supported. Supported models: {', '.join(supported_models)}"
        super().__init__(
            detail=detail,
            error_code=ErrorCode.UNSUPPORTED_MODEL,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AnalysisInProgress(ApoemaException):
    """Analysis is already in progress"""

    def __init__(self, analysis_id: int):
        super().__init__(
            detail=f"Analysis {analysis_id} is already in progress",
            error_code=ErrorCode.INVALID_INPUT,
            status_code=status.HTTP_409_CONFLICT,
        )
