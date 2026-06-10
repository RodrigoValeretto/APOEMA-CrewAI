"""
Input validation functions for APOEMA API
"""
import os
from pathlib import Path
from typing import Tuple
from .constants import (
    AnalysisType,
    ModelType,
    FileType,
    ALLOWED_FILE_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
)
from .exceptions import (
    FileNotFound,
    InvalidAnalysisInput,
    UnsupportedModel,
    InvalidFileType,
    FileTooLarge,
)


def validate_file_path(file_path: str) -> bool:
    """
    Validate that a file exists and is readable

    Args:
        file_path: Path to file

    Returns:
        True if file is valid

    Raises:
        FileNotFound: If file doesn't exist
    """
    if not file_path:
        return True  # File path is optional

    if not os.path.exists(file_path):
        raise FileNotFound(file_path)

    if not os.access(file_path, os.R_OK):
        raise InvalidAnalysisInput(
            f"File is not readable: {file_path}"
        )

    return True


def validate_file_extension(file_path: str, expected_type: FileType) -> bool:
    """
    Validate that file has correct extension

    Args:
        file_path: Path to file
        expected_type: Expected file type (assessment, pdf, png, csv)

    Returns:
        True if extension is valid

    Raises:
        InvalidFileType: If extension is invalid
    """
    if not file_path:
        return True

    file_ext = Path(file_path).suffix.lower()
    allowed_exts = ALLOWED_FILE_EXTENSIONS.get(expected_type.value, [])

    if file_ext not in allowed_exts:
        raise InvalidFileType(
            file_ext,
            allowed_exts,
        )

    return True


def validate_file_size(file_path: str) -> bool:
    """
    Validate that file size doesn't exceed maximum

    Args:
        file_path: Path to file

    Returns:
        True if size is valid

    Raises:
        FileTooLarge: If file exceeds max size
    """
    if not file_path or not os.path.exists(file_path):
        return True

    file_size = os.path.getsize(file_path)

    if file_size > MAX_FILE_SIZE_BYTES:
        raise FileTooLarge(file_size, MAX_FILE_SIZE_BYTES)

    return True


def determine_workflow_type(
    pdf_path: str = None,
    png_path: str = None,
    csv_path: str = None,
) -> str:
    """
    Determine workflow type based on provided files

    Args:
        pdf_path: Path to PDF file (optional)
        png_path: Path to PNG file (optional)
        csv_path: Path to CSV file (optional)

    Returns:
        Workflow type: 'pdf', 'png_csv', or 'basic'

    Raises:
        InvalidAnalysisInput: If file combination is invalid
    """
    has_pdf = pdf_path and os.path.exists(pdf_path)
    has_png = png_path and os.path.exists(png_path)
    has_csv = csv_path and os.path.exists(csv_path)

    # PDF workflow
    if has_pdf:
        if has_png or has_csv:
            raise InvalidAnalysisInput(
                "Cannot mix PDF with PNG+CSV. Provide either PDF or PNG+CSV, not both."
            )
        return AnalysisType.PDF.value

    # PNG+CSV workflow
    if has_png and has_csv:
        return AnalysisType.PNG_CSV.value

    # Partial PNG+CSV
    if has_png and not has_csv:
        raise InvalidAnalysisInput(
            f"PNG file provided but CSV is missing: {csv_path or 'not specified'}"
        )

    if has_csv and not has_png:
        raise InvalidAnalysisInput(
            f"CSV file provided but PNG is missing: {png_path or 'not specified'}"
        )

    # Basic workflow (no PDF, PNG, or CSV)
    return AnalysisType.BASIC.value


def validate_model_choice(model: str) -> bool:
    """
    Validate that model is supported

    Args:
        model: Model name

    Returns:
        True if model is valid

    Raises:
        UnsupportedModel: If model is not supported
    """
    supported_models = [ModelType.GEMINI.value, ModelType.OLLAMA.value]

    if model not in supported_models:
        raise UnsupportedModel(model, supported_models)

    return True


def validate_analysis_request(
    assessment_file: str = None,
    assessment_file_id: int = None,
    pdf_path: str = None,
    pdf_file_id: int = None,
    png_path: str = None,
    png_file_id: int = None,
    csv_path: str = None,
    csv_file_id: int = None,
    model: str = None,
) -> Tuple[bool, str]:
    """
    Validate complete analysis request

    Args:
        assessment_file: Path to assessment file
        assessment_file_id: ID of uploaded assessment file
        pdf_path: Path to PDF file
        pdf_file_id: ID of uploaded PDF file
        png_path: Path to PNG file
        png_file_id: ID of uploaded PNG file
        csv_path: Path to CSV file
        csv_file_id: ID of uploaded CSV file
        model: LLM model to use

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    try:
        # Validate that assessment file is provided (either path or ID)
        if not assessment_file and not assessment_file_id:
            return False, "assessment_file or assessment_file_id must be provided"

        # If assessment_file is provided, validate it
        if assessment_file:
            validate_file_path(assessment_file)
            validate_file_extension(assessment_file, FileType.ASSESSMENT)
            validate_file_size(assessment_file)

        # Validate optional files if provided
        if pdf_path:
            validate_file_path(pdf_path)
            validate_file_extension(pdf_path, FileType.PDF)
            validate_file_size(pdf_path)

        if png_path:
            validate_file_path(png_path)
            validate_file_extension(png_path, FileType.PNG)
            validate_file_size(png_path)

        if csv_path:
            validate_file_path(csv_path)
            validate_file_extension(csv_path, FileType.CSV)
            validate_file_size(csv_path)

        # Validate model
        if model:
            validate_model_choice(model)

        # Determine and validate workflow type
        determine_workflow_type(pdf_path, png_path, csv_path)

        return True, ""

    except Exception as e:
        return False, str(e)


def validate_uploaded_file(
    file_name: str,
    file_size: int,
    file_type: FileType,
) -> Tuple[bool, str]:
    """
    Validate an uploaded file

    Args:
        file_name: Original filename
        file_size: File size in bytes
        file_type: Type of file

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    try:
        # Check file size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise FileTooLarge(file_size, MAX_FILE_SIZE_BYTES)

        # Check file extension
        file_ext = Path(file_name).suffix.lower()
        allowed_exts = ALLOWED_FILE_EXTENSIONS.get(file_type.value, [])

        if file_ext not in allowed_exts:
            raise InvalidFileType(file_ext, allowed_exts)

        return True, ""

    except Exception as e:
        return False, str(e)
