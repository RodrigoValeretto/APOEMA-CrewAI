-- V9: drive-file deduplication for ficha ingestion.
-- Each informativo_document sourced from Google Drive carries the drive file id
-- so re-running the ingestion (startup or POST /api/fichas/ingest) is idempotent:
-- an already-ingested file is never downloaded/registered twice.
ALTER TABLE informativo_documents ADD COLUMN IF NOT EXISTS drive_file_id VARCHAR(255);
CREATE UNIQUE INDEX IF NOT EXISTS idx_informativo_documents_drive_file_id
    ON informativo_documents(drive_file_id)
    WHERE drive_file_id IS NOT NULL;
