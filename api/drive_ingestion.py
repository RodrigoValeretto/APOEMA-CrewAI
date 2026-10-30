"""Google Drive ficha ingestion.

Enumerates a public Drive folder, downloads every CAPES ficha/anexo PDF and
registers it through the existing informativo+conversion pipeline. Idempotent:
dedupes by ``drive_file_id`` so re-running (startup or ``POST /api/fichas/ingest``)
only downloads new files and re-enqueues documents still pending/failed.

Drive specifics:
- folder listing: ``https://drive.google.com/embeddedfolderview?id=<FOLDER>#list``
  returns an HTML page whose entries carry ``id="entry-<fileId>"`` and a
  ``flip-entry-title">NAME.pdf`` node.
- file download: ``https://drive.google.com/uc?export=download&id=<fileId>``
  (no auth needed for public folders).
"""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

from config import get_config
from . import database
from .constants import ConversionStatus, FileType
from .fichas_catalog import (
    area_name,
    ficha_key,
    parse_ficha_filename,
    parse_quadrienio,
)

logger = logging.getLogger(__name__)

_DRIVE_FOLDER_LIST_URL = "https://drive.google.com/embeddedfolderview?id={folder}#list"
_DRIVE_DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"

_ENTRY_RE = re.compile(
    r'id="entry-([A-Za-z0-9_-]{20,})".*?flip-entry-title">([^<]+)</div>', re.S
)


def list_drive_folder(folder_id: str) -> List[Dict[str, str]]:
    """Return ``[{file_id, name}]`` for every file in a public Drive folder."""
    url = _DRIVE_FOLDER_LIST_URL.format(folder=folder_id)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return [
        {"file_id": m.group(1), "name": m.group(2)}
        for m in _ENTRY_RE.finditer(resp.text)
    ]


def download_drive_file(file_id: str) -> bytes:
    """Download a public Drive file's raw bytes."""
    url = _DRIVE_DOWNLOAD_URL.format(file_id=file_id)
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    content = b"".join(resp.iter_content(chunk_size=8192))
    return content


def _save_downloaded_pdf(name: str, content: bytes) -> int:
    """Write a downloaded PDF to the uploads dir and register an analysis_file.

    Returns the new ``analysis_files`` id.
    """
    config = get_config()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
    safe_name = timestamp + Path(name).stem + ".pdf"
    file_path = config.UPLOAD_DIR / safe_name
    file_path.write_bytes(content)
    return database.create_analysis_file(
        file_type=FileType.PDF.value,
        file_name=name,
        file_path=str(file_path),
        file_size=len(content),
    )


def _get_or_create_informativo(slug: str, nome: str, quadrienio: Optional[str]) -> int:
    """Return the informativo id for a slug, creating it on first sight."""
    existing = database.get_informativo_by_slug(slug)
    if existing:
        return existing["id"]
    return database.create_informativo(nome=nome, slug=slug, quadrienio=quadrienio)


def ingest_drive_folder(folder_id: str) -> Dict[str, int]:
    """Enumerate + download + register every ficha/anexo in a Drive folder.

    Returns stats: {total, downloaded, new_documents, reenqueued, skipped, errors}.
    """
    stats = {
        "total": 0,
        "downloaded": 0,
        "new_documents": 0,
        "reenqueued": 0,
        "skipped": 0,
        "errors": 0,
    }

    entries = list_drive_folder(folder_id)
    stats["total"] = len(entries)

    for entry in entries:
        file_id = entry["file_id"]
        name = entry["name"]
        try:
            parsed = parse_ficha_filename(name)
            if parsed is None:
                logger.warning(f"[Ingest] Ignoring unrecognized drive file: {name}")
                stats["skipped"] += 1
                continue
            area_code, kind = parsed
            nome = area_name(area_code)
            if nome is None:
                logger.warning(
                    f"[Ingest] Ignoring drive file with unknown area code '{area_code}': {name}"
                )
                stats["skipped"] += 1
                continue

            # Idempotence: a doc already ingested by drive_file_id is left alone
            # unless it still needs a conversion attempt.
            existing_doc = database.get_informativo_document_by_drive_file_id(file_id)
            if existing_doc:
                if existing_doc["status"] in (
                    ConversionStatus.PENDING.value,
                    ConversionStatus.FAILED.value,
                ):
                    from conversion_tasks import convert_informativo_document

                    convert_informativo_document.send(
                        document_id=existing_doc["id"]
                    )
                    stats["reenqueued"] += 1
                else:
                    stats["skipped"] += 1
                continue

            slug = ficha_key(area_code)
            informativo_id = _get_or_create_informativo(
                slug=slug,
                nome=nome,
                quadrienio=parse_quadrienio(name),
            )

            content = download_drive_file(file_id)
            original_file_id = _save_downloaded_pdf(name, content)
            stats["downloaded"] += 1

            document_id = database.create_informativo_document(
                informativo_id=informativo_id,
                kind=kind,
                original_file_id=original_file_id,
                drive_file_id=file_id,
            )

            from conversion_tasks import convert_informativo_document

            convert_informativo_document.send(document_id=document_id)
            stats["new_documents"] += 1
        except Exception as e:  # per-file isolation: one bad file doesn't abort the run
            logger.exception(f"[Ingest] Failed to ingest drive file {name}: {e}")
            stats["errors"] += 1

    return stats
