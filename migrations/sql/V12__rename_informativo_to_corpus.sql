-- V12: rename the informativo resource to a standardized English surface.
-- Tables:  informativos -> corpora, informativo_documents -> corpus_documents.
-- Columns: informativos.nome -> name, informativos.quadrienio -> quadrennium,
--          informativo_documents.informativo_id -> corpus_id.
-- Values:  document kind  ficha->form, anexo->attachment, adendo->addendum;
--          converted extra file_type  anexo->attachment.

-- 1. Tables
ALTER TABLE informativos RENAME TO corpora;
ALTER TABLE informativo_documents RENAME TO corpus_documents;

-- 2. Columns
ALTER TABLE corpora RENAME COLUMN nome TO name;
ALTER TABLE corpora RENAME COLUMN quadrienio TO quadrennium;
ALTER TABLE corpus_documents RENAME COLUMN informativo_id TO corpus_id;

-- 3. Document kind values (Portuguese -> English)
UPDATE corpus_documents SET kind = 'form' WHERE kind = 'ficha';
UPDATE corpus_documents SET kind = 'attachment' WHERE kind = 'anexo';
UPDATE corpus_documents SET kind = 'addendum' WHERE kind = 'adendo';

-- 4. Converted extra file_type (the anexo/adendo JSON artifacts)
UPDATE analysis_files SET file_type = 'attachment' WHERE file_type = 'anexo';
UPDATE analysis_file_mapping SET file_type = 'attachment' WHERE file_type = 'anexo';

-- 5. Indexes, constraints and sequences (keep names consistent with new tables)
ALTER INDEX informativos_pkey RENAME TO corpora_pkey;
ALTER INDEX informativos_slug_key RENAME TO corpora_slug_key;
ALTER INDEX informativo_documents_pkey RENAME TO corpus_documents_pkey;
ALTER INDEX idx_informativo_documents_informativo RENAME TO idx_corpus_documents_corpus;
ALTER INDEX idx_informativo_documents_status RENAME TO idx_corpus_documents_status;
ALTER INDEX idx_informativo_documents_drive_file_id RENAME TO idx_corpus_documents_drive_file_id;

ALTER SEQUENCE informativos_id_seq RENAME TO corpora_id_seq;
ALTER SEQUENCE informativo_documents_id_seq RENAME TO corpus_documents_id_seq;

ALTER TABLE analysis RENAME CONSTRAINT analysis_informativo_id_fkey TO analysis_corpus_id_fkey;
ALTER TABLE corpus_documents RENAME CONSTRAINT informativo_documents_informativo_id_fkey TO corpus_documents_corpus_id_fkey;
ALTER TABLE corpus_documents RENAME CONSTRAINT informativo_documents_converted_file_id_fkey TO corpus_documents_converted_file_id_fkey;
ALTER TABLE corpus_documents RENAME CONSTRAINT informativo_documents_original_file_id_fkey TO corpus_documents_original_file_id_fkey;
