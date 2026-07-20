-- Initial schema setup for APOEMA
-- Creates base tables for analysis tracking

-- Table for analysis
CREATE TABLE IF NOT EXISTS analysis (
    id SERIAL PRIMARY KEY,
    type VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for analysis results
CREATE TABLE IF NOT EXISTS analysis_results (
    id SERIAL PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES analysis(id) ON DELETE CASCADE,
    task_name VARCHAR(255) NOT NULL,
    result TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX idx_analysis_type ON analysis(type);
CREATE INDEX idx_analysis_status ON analysis(status);
CREATE INDEX idx_analysis_created_at ON analysis(created_at);
CREATE INDEX idx_analysis_results_analysis_id ON analysis_results(analysis_id);
CREATE INDEX idx_analysis_results_task_name ON analysis_results(task_name);
CREATE INDEX idx_analysis_results_created_at ON analysis_results(created_at);