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
import re
import unicodedata


def slugify(text: str) -> str:
    """Slugify an informativo name (NFKD -> ascii lowercase, _ separators)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return text or "informativo"


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


def validate_mutual_exclusivity(
    assessment_file: str = None,
    assessment_file_id: int = None,
    assessment_file_url: str = None,
    pdf_path: str = None,
    pdf_file_id: int = None,
    pdf_url: str = None,
    png_path: str = None,
    png_file_id: int = None,
    png_url: str = None,
    csv_path: str = None,
    csv_file_id: int = None,
    csv_url: str = None,
) -> None:
    """
    Validate that for each file type, only one source is provided (path, ID, or URL)

    Args:
        assessment_file: Path to assessment file
        assessment_file_id: ID of uploaded assessment file
        assessment_file_url: URL to assessment file
        pdf_path: Path to PDF file
        pdf_file_id: ID of uploaded PDF file
        pdf_url: URL to PDF file
        png_path: Path to PNG file
        png_file_id: ID of uploaded PNG file
        png_url: URL to PNG file
        csv_path: Path to CSV file
        csv_file_id: ID of uploaded CSV file
        csv_url: URL to CSV file

    Raises:
        InvalidAnalysisInput: If multiple sources are provided for the same file type
    """
    # Check assessment file
    sources_count = sum([
        bool(assessment_file),
        bool(assessment_file_id),
        bool(assessment_file_url)
    ])
    if sources_count > 1:
        raise InvalidAnalysisInput(
            "Only one source can be provided for assessment_file (path, ID, or URL)"
        )

    # Check PDF file
    sources_count = sum([
        bool(pdf_path),
        bool(pdf_file_id),
        bool(pdf_url)
    ])
    if sources_count > 1:
        raise InvalidAnalysisInput(
            "Only one source can be provided for pdf (path, ID, or URL)"
        )

    # Check PNG file
    sources_count = sum([
        bool(png_path),
        bool(png_file_id),
        bool(png_url)
    ])
    if sources_count > 1:
        raise InvalidAnalysisInput(
            "Only one source can be provided for png (path, ID, or URL)"
        )

    # Check CSV file
    sources_count = sum([
        bool(csv_path),
        bool(csv_file_id),
        bool(csv_url)
    ])
    if sources_count > 1:
        raise InvalidAnalysisInput(
            "Only one source can be provided for csv (path, ID, or URL)"
        )


def validate_analysis_request(
    assessment_file: str = None,
    assessment_file_id: int = None,
    assessment_file_url: str = None,
    pdf_path: str = None,
    pdf_file_id: int = None,
    pdf_url: str = None,
    png_path: str = None,
    png_file_id: int = None,
    png_url: str = None,
    csv_path: str = None,
    csv_file_id: int = None,
    csv_url: str = None,
    model: str = None,
    informativo_id: int = None,
) -> Tuple[bool, str]:
    """
    Validate complete analysis request

    Args:
        assessment_file: Path to assessment file
        assessment_file_id: ID of uploaded assessment file
        assessment_file_url: URL to assessment file
        pdf_path: Path to PDF file
        pdf_file_id: ID of uploaded PDF file
        pdf_url: URL to PDF file
        png_path: Path to PNG file
        png_file_id: ID of uploaded PNG file
        png_url: URL to PNG file
        csv_path: Path to CSV file
        csv_file_id: ID of uploaded CSV file
        csv_url: URL to CSV file
        model: LLM model to use

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    try:
        # Validate mutual exclusivity (only one source per file type)
        validate_mutual_exclusivity(
            assessment_file=assessment_file,
            assessment_file_id=assessment_file_id,
            assessment_file_url=assessment_file_url,
            pdf_path=pdf_path,
            pdf_file_id=pdf_file_id,
            pdf_url=pdf_url,
            png_path=png_path,
            png_file_id=png_file_id,
            png_url=png_url,
            csv_path=csv_path,
            csv_file_id=csv_file_id,
            csv_url=csv_url,
        )

        # Validate that assessment input comes from ONE source: either an
        # explicit assessment file (path/ID/URL) or an informativo whose
        # converted ficha plays that role.
        has_assessment_source = bool(assessment_file or assessment_file_id or assessment_file_url)
        if informativo_id and has_assessment_source:
            return (
                False,
                "informativo_id cannot be combined with assessment_file / "
                "assessment_file_id / assessment_file_url",
            )
        if not informativo_id and not has_assessment_source:
            return False, "assessment_file, assessment_file_id, assessment_file_url, or informativo_id must be provided"

        # Validate URLs
        if assessment_file_url:
            validate_url(assessment_file_url)

        if pdf_url:
            validate_url(pdf_url)

        if png_url:
            validate_url(png_url)

        if csv_url:
            validate_url(csv_url)

        # If file path is provided (not URL), validate it
        if assessment_file:
            validate_file_path(assessment_file)
            validate_file_extension(assessment_file, FileType.ASSESSMENT)
            validate_file_size(assessment_file)

        # Validate optional files if provided (not URLs)
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


def validate_url(url: str) -> bool:
    """
    Validate that a URL is safe and properly formatted

    Args:
        url: URL to validate

    Returns:
        True if URL is valid

    Raises:
        InvalidAnalysisInput: If URL is invalid or not HTTPS/HTTP
    """
    from urllib.parse import urlparse
    import ipaddress

    if not url:
        raise InvalidAnalysisInput("URL cannot be empty")

    try:
        parsed = urlparse(url)

        # Check protocol
        if parsed.scheme not in ("http", "https"):
            raise InvalidAnalysisInput(
                f"Invalid protocol: {parsed.scheme}. Only http and https are allowed."
            )

        # Check hostname exists
        if not parsed.netloc:
            raise InvalidAnalysisInput("Invalid URL: missing hostname")

        # Extract hostname without port
        hostname = parsed.hostname or parsed.netloc

        # Reject localhost and 127.0.0.1 (SSRF protection)
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            raise InvalidAnalysisInput(
                f"URL cannot point to localhost or loopback address: {hostname}"
            )

        # Reject private IP ranges (SSRF protection)
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise InvalidAnalysisInput(
                    f"URL cannot point to private or reserved IP address: {hostname}"
                )
        except ValueError:
            # Not an IP address, that's OK
            pass

        return True

    except InvalidAnalysisInput:
        raise
    except Exception as e:
        raise InvalidAnalysisInput(f"Invalid URL: {str(e)}")
