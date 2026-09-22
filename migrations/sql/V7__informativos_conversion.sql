-- V7: informativos (corpus de documentos por área CAPES) + conversão PDF/XLSX -> JSON

-- Corpus de documentos de uma área de conhecimento (ex.: "Ciência da Computação")
CREATE TABLE IF NOT EXISTS informativos (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    slug VARCHAR(255) NOT NULL UNIQUE,
    quadrienio VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Documentos de um informativo e o status da conversão para JSON
-- kind: ficha | anexo | adendo
-- status: pending | processing | completed | failed
CREATE TABLE IF NOT EXISTS informativo_documents (
    id SERIAL PRIMARY KEY,
    informativo_id INTEGER NOT NULL REFERENCES informativos(id) ON DELETE CASCADE,
    kind VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    original_file_id INTEGER REFERENCES analysis_files(id),
    converted_file_id INTEGER REFERENCES analysis_files(id),
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_informativo_documents_informativo ON informativo_documents(informativo_id);
CREATE INDEX idx_informativo_documents_status ON informativo_documents(status);

-- Proveniência: análise disparada a partir de um informativo
ALTER TABLE analysis ADD COLUMN IF NOT EXISTS informativo_id INTEGER REFERENCES informativos(id);
