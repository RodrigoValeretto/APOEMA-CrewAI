-- V11: rename the analysis's informativo reference to a standardized English
-- name. The `informativo` resource (tables `informativos` / `informativo_documents`
-- and the `/api/informativos/*` endpoints) keeps its name; only the attribute on
-- the `analysis` row — the foreign reference to that corpus — is renamed, because
-- `informativo_id` mixed Portuguese with the English field names around it.
ALTER TABLE analysis RENAME COLUMN informativo_id TO corpus_id;
