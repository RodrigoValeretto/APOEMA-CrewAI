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
    }

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
    # phi4-mini:3.8b fits comfortably in Docker Desktop's default ~7.65 GiB memory
    # limit and is strong at structured output (no thinking-mode overhead like qwen3).
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi4-mini:3.8b")
    # Vision model used by the plot analyst (task 7 reads a PNG chart).
    OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "qwen2.5vl:3b")
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "ollama")

    # Embedding model used by CrewAI's native Knowledge feature (feeds the
    # assessment file into agents via automatic retrieval + injection).
    RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "nomic-embed-text")

    # Task Configuration
    TASK_TIMEOUT_MINUTES = int(os.getenv("TASK_TIMEOUT_MINUTES", 60))
    TASK_TIMEOUT_SECONDS = TASK_TIMEOUT_MINUTES * 60

    # Pagination
    DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", 10))
    MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", 100))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    def __init__(self):
        """Initialize and create necessary directories"""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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

    DEBUG = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = False
    LOG_LEVEL = "INFO"
    # In production, CORS should be more restrictive
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")


class TestingConfig(Config):
    """Testing configuration"""

    DEBUG = True
    DB_NAME = "apoema_test_db"
    LOG_LEVEL = "DEBUG"


# Determine which config to use
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
