"""
Centralized configuration management for APOEMA
"""
import os
from pathlib import Path
from typing import List


class Config:
    """Base configuration"""

    # Project paths
    PROJECT_ROOT = Path(__file__).parent
    UPLOAD_DIR = PROJECT_ROOT / "uploads"
    MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "sql"

    # Database Configuration
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", 5432))
    DB_USER = os.getenv("DB_USER", "apoema")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "apoema_dev_password")
    DB_NAME = os.getenv("DB_NAME", "apoema_db")
    # Connection pool sizing. Every query used to open/close a fresh psycopg
    # connection, which under the FIFO backoff loop produced ~27k TIME_WAIT
    # sockets and exhausted the ephemeral-port range (intermittent
    # "Cannot assign requested address"). A small pool reuses connections and
    # eliminates the connect/close churn entirely.
    DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
    DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "20"))

    @property
    def DATABASE_URL(self) -> str:
        """Construct database URL"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # RabbitMQ Configuration
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", 5672))
    RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")

    @property
    def RABBITMQ_URL(self) -> str:
        """Construct RabbitMQ URL"""
        rabbitmq_url = os.getenv("RABBITMQ_URL")
        if rabbitmq_url:
            return rabbitmq_url
        return f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}//"

    # API Configuration
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", 8000))
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"

    # CORS Configuration
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8080",
        os.getenv("CORS_ORIGINS", ""),
    ]
    CORS_ORIGINS = [origin for origin in CORS_ORIGINS if origin]  # Filter empty strings

    # File Configuration
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 50))
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
    ALLOWED_FILE_EXTENSIONS = {
        "assessment": [".json"],
        "pdf": [".pdf"],
        "png": [".png"],
        "csv": [".csv"],
        "xlsx": [".xlsx"],
    }

    # Document conversion (corpus PDFs/XLSXs -> JSON)
    CONVERTER_DIR = UPLOAD_DIR / "converted"
    # CAPES forms/reports têm camada de texto; OCR (docling) só sob demanda
    CONVERTER_OCR = os.getenv("CONVERTER_OCR", "false").lower() == "true"

    # Google Drive ficha ingestion
    DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")
    DRIVE_AUTO_INGEST = os.getenv("DRIVE_AUTO_INGEST", "true").lower() == "true"

    # LLM Configuration
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    # Ollama base URL. Prefer OLLAMA_BASE_URL, but fall back to OLLAMA_HOST so the
    # LLM and the Knowledge embedder use the same endpoint (docker-compose sets
    # OLLAMA_HOST).
    OLLAMA_BASE_URL = os.getenv(
        "OLLAMA_BASE_URL", os.getenv("OLLAMA_HOST", "http://localhost:11434")
    )
    # Ollama chat model used by the "ollama" profile (must support tool calling).
    # qwen2.5:3b (1.9GB) is the CPU-safe default; on GPU machines set
    # OLLAMA_MODEL=qwen2.5:7b (4.7GB) in .env (fits an RTX 4060 8GB).
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    # Vision model used by the plot analyst (task 7 reads a PNG chart).
    OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "ollama")

    # Embedding model used by CrewAI's native Knowledge feature (feeds the
    # assessment file into agents via automatic retrieval + injection).
    RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "nomic-embed-text")

    # Task Configuration
    TASK_TIMEOUT_MINUTES = int(os.getenv("TASK_TIMEOUT_MINUTES", 60))
    TASK_TIMEOUT_SECONDS = TASK_TIMEOUT_MINUTES * 60

    # Analysis gate concurrency. Controls how many analyses may be 'processing'
    # at once — the FIFO gate's slot count. docker-compose reads the same var
    # into `dramatiq --processes N --threads 1`, so the worker's process/thread
    # count tracks the gate (one consumer thread per slot). Default 1 = the
    # original single-analysis-at-a-time FIFO; raise it on a machine with spare
    # RAM/VRAM to drain the queue faster.
    ANALYSIS_CONCURRENCY = max(1, int(os.getenv("ANALYSIS_CONCURRENCY", "1")))

    # Gate requeue backoff. A pending analysis that is not yet at the head of
    # the FIFO queue re-checks the gate after a delay that grows with its
    # position in the queue (base * (position + 1) ms, capped at max). The old
    # flat 2s delay turned ~700 pending analyses into a ~350 msg/s requeue storm
    # (queue churn + --verbose log spam) that OOM-killed the worker.
    GATE_RECHECK_BASE_DELAY_MS = int(os.getenv("GATE_RECHECK_BASE_DELAY_MS", "2000"))
    GATE_RECHECK_MAX_DELAY_MS = int(os.getenv("GATE_RECHECK_MAX_DELAY_MS", "60000"))

    # Pagination
    DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", 10))
    MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", 100))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    def __init__(self):
        """Initialize and create necessary directories"""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.CONVERTER_DIR.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        """Convert configuration to dictionary"""
        return {
            "db_host": self.DB_HOST,
            "db_port": self.DB_PORT,
            "db_name": self.DB_NAME,
            "api_host": self.API_HOST,
            "api_port": self.API_PORT,
            "debug": self.DEBUG,
            "upload_dir": str(self.UPLOAD_DIR),
            "max_file_size_mb": self.MAX_FILE_SIZE_MB,
            "default_model": self.DEFAULT_MODEL,
            "task_timeout_minutes": self.TASK_TIMEOUT_MINUTES,
        }


class DevelopmentConfig(Config):
    """Development configuration"""

    DEBUG = os.getenv("DEBUG", "True").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    # In production, CORS should be more restrictive
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")


class TestingConfig(Config):
    """Testing configuration"""

    DEBUG = True
    DB_NAME = "apoema_test_db"
    LOG_LEVEL = "DEBUG"


# Determine which config to use. The env vars are read lazily by each class so
# that ``DEBUG``/``LOG_LEVEL`` set on the container actually take effect — the
# hardcoded class attributes below previously OVERRODE the ``DEBUG`` value the
# compose file passed, which kept uvicorn's auto-reload on in production and
# killed the app on any bind-mounted code change.
_ENV = os.getenv("ENV", "development").lower()

if _ENV == "production":
    config = ProductionConfig()
elif _ENV == "testing":
    config = TestingConfig()
else:
    config = DevelopmentConfig()


def get_config() -> Config:
    """Get current configuration instance"""
    return config
