"""Dramatiq actors for informativo document -> JSON conversion.

Runs on the dedicated ``conversion`` queue (see the ``converter_worker``
service in docker-compose) so long-running docling jobs never block the
analysis FIFO queue. Docling is imported lazily inside the actor body.
"""
import json
import logging
import os

import dramatiq
# Expõe o broker no módulo: o CLI do dramatiq 1.18 exige o positional `broker`
# (módulo com atributo `broker`) — mesmo padrão do tasks.py.
from dramatiq_broker import broker  # noqa: F401

from api import database
from api.constants import (
    CONVERTED_FICHA_FILE_TYPE,
    CONVERTED_EXTRA_FILE_TYPE,
    ConversionStatus,
)
from config import get_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dramatiq.actor(
    queue_name="conversion",
    max_retries=1,
    time_limit=1_800_000,  # 30 min covers model download + large PDFs
    min_backoff=10_000,
    max_backoff=60_000,
)
def convert_informativo_document(document_id: int) -> dict:
    """Convert one informativo document (ficha/anexo/adendo) to JSON.

    Flow: pending -> processing -> completed (converted_file_id set) | failed.
    Re-running a completed/failed job is a no-op (idempotent).
    """
    try:
        # Atomic claim: only one worker converts a given document.
        if not database.claim_informativo_document(document_id):
            doc = database.get_informativo_document(document_id)
            logger.info(f"[Doc {document_id}] Not claimed (status={doc['status']})")
            return {"document_id": document_id, "status": doc["status"]}

        doc = database.get_informativo_document(document_id)
        informativo = database.get_informativo(doc["informativo_id"])
        source_path = doc.get("original_file_path")
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError(f"Source file missing: {source_path}")

        logger.info(
            f"[Doc {document_id}] Converting {doc['kind']} "
            f"{os.path.basename(source_path)} (informativo {informativo['slug']})..."
        )
        from conversion.engine import convert_source_file  # lazy: torch

        config = get_config()
        output = convert_source_file(
            source_path,
            kind=doc["kind"],
            informativo=informativo["slug"],
            quadrienio=informativo.get("quadrienio"),
            do_ocr=config.CONVERTER_OCR,
        )

        out_path = config.CONVERTER_DIR / f"doc_{document_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        file_type = (
            CONVERTED_FICHA_FILE_TYPE
            if doc["kind"] == "ficha"
            else CONVERTED_EXTRA_FILE_TYPE
        )
        converted_file_id = database.create_analysis_file(
            file_type=file_type,
            file_name=out_path.name,
            file_path=str(out_path),
            file_size=out_path.stat().st_size,
        )
        database.update_informativo_document_status(
            document_id,
            ConversionStatus.COMPLETED.value,
            converted_file_id=converted_file_id,
            error=None,
        )
        logger.info(f"[Doc {document_id}] Conversion completed -> file {converted_file_id}")
        return {
            "document_id": document_id,
            "status": ConversionStatus.COMPLETED.value,
            "converted_file_id": converted_file_id,
        }
    except Exception as e:  # deterministic failures: record and stop (no retry churn)
        logger.error(f"[Doc {document_id}] Conversion failed: {e}")
        logger.exception(e)
        try:
            database.update_informativo_document_status(
                document_id,
                ConversionStatus.FAILED.value,
                error=str(e)[:2000],
            )
        except Exception:
            logger.exception(f"[Doc {document_id}] Failed to persist error status")
        return {
            "document_id": document_id,
            "status": ConversionStatus.FAILED.value,
            "error": str(e)[:2000],
        }
