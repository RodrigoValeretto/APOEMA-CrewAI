"""
Middleware for FastAPI application
Handles CORS, error handling, and request logging
"""
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import logging
import time
from config import get_config

config = get_config()

# Setup logging
logging.basicConfig(level=config.LOG_LEVEL)
logger = logging.getLogger(__name__)


def add_cors_middleware(app: FastAPI):
    """Add CORS middleware to FastAPI app"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"CORS enabled for origins: {config.CORS_ORIGINS}")


async def logging_middleware(request: Request, call_next):
    """Middleware to log requests and responses"""
    # Log request
    logger.info(f"→ {request.method} {request.url.path}")

    # Record start time
    start_time = time.time()

    # Process request
    response = await call_next(request)

    # Calculate duration
    duration = time.time() - start_time

    # Log response
    logger.info(
        f"← {request.method} {request.url.path} {response.status_code} ({duration:.3f}s)"
    )

    # Add custom headers
    response.headers["X-Process-Time"] = str(duration)

    return response


def add_error_handlers(app: FastAPI):
    """Add error handlers to FastAPI app"""

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle general exceptions"""
        logger.error(
            f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
            exc_info=True,
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "timestamp": datetime.now().isoformat(),
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """Handle validation errors"""
        logger.warning(f"Validation error: {str(exc)}")

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "VALIDATION_ERROR",
                "message": str(exc),
                "timestamp": datetime.now().isoformat(),
            },
        )

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request: Request, exc: FileNotFoundError):
        """Handle file not found errors"""
        logger.warning(f"File not found: {str(exc)}")

        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "FILE_NOT_FOUND",
                "message": str(exc),
                "timestamp": datetime.now().isoformat(),
            },
        )


def setup_middleware(app: FastAPI):
    """Setup all middleware for the application"""
    # Add CORS
    add_cors_middleware(app)

    # Add logging middleware
    app.middleware("http")(logging_middleware)

    # Add error handlers
    add_error_handlers(app)

    logger.info("Middleware setup completed")
