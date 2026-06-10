"""
File management utilities for APOEMA API
"""
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple
from fastapi import UploadFile
import hashlib
from config import get_config
from .exceptions import FileUploadError, FileTooLarge, InvalidFileType
from .constants import FileType, ALLOWED_FILE_EXTENSIONS, MAX_FILE_SIZE_BYTES
from .validators import validate_uploaded_file
from . import database


config = get_config()


def ensure_upload_dir() -> Path:
    """Ensure upload directory exists"""
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return config.UPLOAD_DIR


def calculate_file_hash(file_path: str) -> str:
    """
    Calculate SHA256 hash of a file

    Args:
        file_path: Path to file

    Returns:
        Hex hash string
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


async def save_uploaded_file(
    upload_file: UploadFile,
    file_type: FileType,
    analysis_id: Optional[int] = None,
) -> Tuple[int, str]:
    """
    Save an uploaded file to disk and create tracking record

    Args:
        upload_file: FastAPI UploadFile
        file_type: Type of file being uploaded
        analysis_id: Optional ID of associated analysis

    Returns:
        Tuple of (file_id, file_path)

    Raises:
        FileTooLarge: If file exceeds maximum size
        InvalidFileType: If file type is invalid
        FileUploadError: If save fails
    """
    try:
        ensure_upload_dir()

        # Read file content
        file_content = await upload_file.read()
        file_size = len(file_content)

        # Validate file
        is_valid, error_msg = validate_uploaded_file(
            upload_file.filename,
            file_size,
            file_type,
        )
        if not is_valid:
            raise FileUploadError(error_msg)

        # Generate filename with timestamp to avoid conflicts
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
        file_ext = Path(upload_file.filename).suffix
        safe_filename = timestamp + Path(upload_file.filename).stem + file_ext
        file_path = config.UPLOAD_DIR / safe_filename

        # Save file
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Calculate hash
        file_hash = calculate_file_hash(str(file_path))

        # Create database record
        file_id = database.create_analysis_file(
            analysis_id=analysis_id,
            file_type=file_type.value,
            file_name=upload_file.filename,
            file_path=str(file_path),
            file_size=file_size,
        )

        return file_id, str(file_path)

    except (FileTooLarge, InvalidFileType, FileUploadError):
        raise
    except Exception as e:
        raise FileUploadError(f"Failed to save file: {str(e)}")


def delete_file(file_id: int) -> None:
    """
    Delete a file from disk and remove tracking record

    Args:
        file_id: ID of file to delete

    Raises:
        FileUploadError: If deletion fails
    """
    try:
        # Get file record
        file_record = database.get_analysis_file(file_id)
        if not file_record:
            return

        file_path = file_record.get("file_path")

        # Delete file from disk
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                # Log but don't fail if file deletion fails
                print(f"Warning: Failed to delete file {file_path}: {str(e)}")

        # Delete database record
        database.delete_analysis_file(file_id)

    except Exception as e:
        raise FileUploadError(f"Failed to delete file: {str(e)}")


def get_file_path(file_id: int) -> Optional[str]:
    """
    Get file path by ID

    Args:
        file_id: ID of file

    Returns:
        File path or None if not found
    """
    file_record = database.get_analysis_file(file_id)
    if file_record:
        return file_record.get("file_path")
    return None


def cleanup_analysis_files(analysis_id: int) -> None:
    """
    Delete all files associated with an analysis

    Args:
        analysis_id: ID of analysis
    """
    try:
        with database.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, file_path FROM analysis_files WHERE analysis_id = %s",
                    (analysis_id,),
                )
                files = cur.fetchall()

                for file_id, file_path in files:
                    # Delete from disk
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            print(f"Warning: Failed to delete {file_path}: {str(e)}")

                # Delete records (cascade happens automatically)

    except Exception as e:
        print(f"Warning: Failed to cleanup files for analysis {analysis_id}: {str(e)}")


def clear_stale_uploads(max_age_hours: int = 24) -> int:
    """
    Clean up uploaded files older than specified age

    Args:
        max_age_hours: Maximum age in hours

    Returns:
        Number of files deleted
    """
    import time
    try:
        from datetime import datetime, timedelta

        deleted_count = 0
        cutoff_time = time.time() - (max_age_hours * 3600)

        upload_dir = ensure_upload_dir()
        for file_path in upload_dir.iterdir():
            if file_path.is_file():
                if file_path.stat().st_mtime < cutoff_time:
                    try:
                        file_path.unlink()
                        deleted_count += 1
                    except Exception as e:
                        print(f"Warning: Failed to delete {file_path}: {str(e)}")

        return deleted_count

    except Exception as e:
        print(f"Warning: Failed to clear stale uploads: {str(e)}")
        return 0
