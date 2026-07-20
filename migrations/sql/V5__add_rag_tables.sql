-- V5: Add RAG (Retrieval-Augmented Generation) tables using pgvector
-- Enables semantic search over PDF reports, assessment JSONs, and Docling extractions

-- Enable the pgvector extension if not already enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Table: rag_documents
-- Represents a source document indexed in the RAG system
CREATE TABLE IF NOT EXISTS rag_documents (
    id SERIAL PRIMARY KEY,
    source_path VARCHAR(1024) NOT NULL,         -- Original file path (e.g., input/cc_report.pdf)
    source_type VARCHAR(50) NOT NULL,            -- pdf, json, docling_json, csv, txt
    title VARCHAR(512),                          -- Document title extracted from content
    file_hash VARCHAR(64),                       -- SHA256 for deduplication
    metadata JSONB DEFAULT '{}',                 -- Flexible metadata (page count, CAPES area, etc.)
    chunk_count INTEGER DEFAULT 0,               -- Number of chunks created
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: rag_chunks
-- Individual text chunks extracted from documents with their vector embeddings
CREATE TABLE IF NOT EXISTS rag_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,                -- Position of this chunk within the document
    content TEXT NOT NULL,                       -- The actual text content of the chunk
    content_hash VARCHAR(64),                    -- Hash for deduplication
    embedding VECTOR(768),                       -- Embedding vector (768 dims for nomic-embed-text / multilingual-e5-large)
    embedding_model VARCHAR(128),                -- Name of the embedding model used
    metadata JSONB DEFAULT '{}',                 -- Chunk-specific metadata (page, section, etc.)
    token_count INTEGER,                         -- Approximate token count
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, chunk_index)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_rag_documents_source_type ON rag_documents(source_type);
CREATE INDEX IF NOT EXISTS idx_rag_documents_file_hash ON rag_documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document_id ON rag_chunks(document_id);

-- Vector similarity index using IVFFlat for fast approximate nearest neighbor search
-- This requires the table to have data before creation, so we use a conditional approach
-- The index will be created after data population via the indexing script
-- CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Add a function to perform similarity search
CREATE OR REPLACE FUNCTION search_rag_chunks(
    query_embedding VECTOR(768),
    match_limit INTEGER DEFAULT 5,
    similarity_threshold FLOAT DEFAULT 0.3
)
RETURNS TABLE (
    chunk_id INTEGER,
    document_id INTEGER,
    document_title VARCHAR(512),
    source_path VARCHAR(1024),
    source_type VARCHAR(50),
    chunk_index INTEGER,
    content TEXT,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        rc.id AS chunk_id,
        rc.document_id,
        rd.title AS document_title,
        rd.source_path,
        rd.source_type,
        rc.chunk_index,
        rc.content,
        1 - (rc.embedding <=> query_embedding) AS similarity
    FROM rag_chunks rc
    JOIN rag_documents rd ON rc.document_id = rd.id
    WHERE 1 - (rc.embedding <=> query_embedding) > similarity_threshold
    ORDER BY rc.embedding <=> query_embedding
    LIMIT match_limit;
END;
$$ LANGUAGE plpgsql;
