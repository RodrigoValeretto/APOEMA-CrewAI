-- API Tables for file tracking and progress monitoring

-- Table for uploaded files tracking
CREATE TABLE IF NOT EXISTS analysis_files (
    id SERIAL PRIMARY KEY,
    analysis_id INTEGER REFERENCES analysis(id) ON DELETE CASCADE,
    file_type VARCHAR(50) NOT NULL, -- assessment, pdf, png, csv
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    file_size BIGINT NOT NULL,
    content_hash VARCHAR(64), -- SHA256 for deduplication
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Progress tracking table (optional, for future enhancements)
CREATE TABLE IF NOT EXISTS analysis_progress (
    id SERIAL PRIMARY KEY,
    analysis_id INTEGER REFERENCES analysis(id) ON DELETE CASCADE,
    current_task INTEGER,
    total_tasks INTEGER,
    percentage_complete FLOAT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX idx_analysis_files_analysis_id ON analysis_files(analysis_id);
CREATE INDEX idx_analysis_files_type ON analysis_files(file_type);
CREATE INDEX idx_analysis_files_created_at ON analysis_files(created_at);

CREATE INDEX idx_analysis_progress_analysis_id ON analysis_progress(analysis_id);
CREATE INDEX idx_analysis_progress_updated_at ON analysis_progress(updated_at);
