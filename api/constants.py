"""
Constants, enums, and configuration values for APOEMA API
"""
from enum import Enum


class AnalysisType(str, Enum):
    """Types of analysis workflows"""
    PDF = "pdf"
    PNG_CSV = "png_csv"
    BASIC = "basic"


class AnalysisStatus(str, Enum):
    """Status of an analysis"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelType(str, Enum):
    """Supported LLM models"""
    GEMINI = "gemini"
    OLLAMA = "ollama"


class FileType(str, Enum):
    """Types of files that can be uploaded"""
    ASSESSMENT = "assessment"
    PDF = "pdf"
    PNG = "png"
    CSV = "csv"
    XLSX = "xlsx"


class DocumentKind(str, Enum):
    """Kinds of documents inside an informativo (CAPES area corpus)"""
    FICHA = "ficha"
    ANEXO = "anexo"
    ADENDO = "adendo"


class ConversionStatus(str, Enum):
    """Status of a document -> JSON conversion job"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# File types used for converted JSON artifacts registered in analysis_files
CONVERTED_FICHA_FILE_TYPE = FileType.ASSESSMENT.value  # drop-in assessment source
CONVERTED_EXTRA_FILE_TYPE = "anexo"  # anexos/adendos converted to JSON


class TaskName(str, Enum):
    """Names of CrewAI tasks"""
    TASK_1_DATA_ANALYSIS = "task_1_data_analysis"
    TASK_2_SUMMARIZATION = "task_2_summarization"
    TASK_3_EXTRACT_PLOTS = "task_3_extract_plots"
    TASK_4_ANALYZE_PLOTS = "task_4_analyze_plots"
    TASK_5_CRITERIA_MAPPING = "task_5_criteria_mapping"
    TASK_6_UTILITY_ASSESSMENT = "task_6_utility_assessment"
    TASK_7_PLOT_DATA_ANALYSIS = "task_7_plot_data_analysis"
    TASK_8_PLOT_INSIGHTS = "task_8_plot_insights"
    TASK_9_PLOT_UTILITY_IMPORTANCE = "task_9_plot_utility_importance"


class ErrorCode(str, Enum):
    """Error codes for API responses"""
    ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
    INVALID_ANALYSIS_STATE = "INVALID_ANALYSIS_STATE"
    INVALID_INPUT = "INVALID_INPUT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    DATABASE_ERROR = "DATABASE_ERROR"
    FILE_UPLOAD_ERROR = "FILE_UPLOAD_ERROR"
    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNSUPPORTED_MODEL = "UNSUPPORTED_MODEL"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    INVALID_URL = "INVALID_URL"
    URL_FETCH_ERROR = "URL_FETCH_ERROR"
    INFORMATIVO_NOT_FOUND = "INFORMATIVO_NOT_FOUND"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"


# Configuration constants
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_FILE_EXTENSIONS = {
    FileType.ASSESSMENT.value: [".json"],
    FileType.PDF.value: [".pdf"],
    FileType.PNG.value: [".png"],
    FileType.CSV.value: [".csv"],
    FileType.XLSX.value: [".xlsx"],
}

# Source extensions accepted per informativo document kind
KIND_ALLOWED_EXTENSIONS = {
    DocumentKind.FICHA.value: [".pdf"],
    DocumentKind.ANEXO.value: [".pdf", ".xlsx"],
    DocumentKind.ADENDO.value: [".pdf", ".xlsx"],
}

TASK_TIMEOUT_MINUTES = 60
TASK_TIMEOUT_SECONDS = TASK_TIMEOUT_MINUTES * 60

# Expected number of tasks per workflow type
EXPECTED_TASKS = {
    AnalysisType.PDF.value: 6,        # Tasks 1, 2, 3, 4, 5, 6
    AnalysisType.PNG_CSV.value: 5,    # Tasks 1, 2, 7, 8, 9
    AnalysisType.BASIC.value: 2,      # Tasks 1, 2
}

# HTTP Status Codes
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
HTTP_INTERNAL_SERVER_ERROR = 500
HTTP_SERVICE_UNAVAILABLE = 503

# Default values
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
DEFAULT_MODEL = ModelType.OLLAMA.value

# Pagination
DEFAULT_SKIP = 0
DEFAULT_LIMIT = 10

# API paths
API_PREFIX = "/api"
HEALTH_PATH = "/health"
ANALYSIS_BASE_PATH = f"{API_PREFIX}/analysis"
FILES_BASE_PATH = f"{API_PREFIX}/files"
