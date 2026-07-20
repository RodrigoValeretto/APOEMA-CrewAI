"""
Entry point for running the APOEMA FastAPI application

Usage:
    python run_api.py

Or with uvicorn directly:
    uvicorn api.api:app --host 0.0.0.0 --port 8000 --reload
"""
import uvicorn
from config import get_config

if __name__ == "__main__":
    config = get_config()

    uvicorn.run(
        "api.api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG,
        log_level=config.LOG_LEVEL.lower(),
    )
