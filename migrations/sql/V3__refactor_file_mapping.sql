-- Refactor analysis_files to use a mapping table for N:M relationships
-- Allows multiple analyses to share the same file

-- 1. Create the analysis_file_mapping junction table
CREATE TABLE IF NOT EXISTS analysis_file_mapping (
    id SERIAL PRIMARY KEY,
    analysis_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(analysis_id, file_id),
    FOREIGN KEY (analysis_id) REFERENCES analysis(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES analysis_files(id) ON DELETE RESTRICT
);

-- 2. Migrate existing data from analysis_files.analysis_id to the mapping table
-- Only migrate records where analysis_id is not NULL
INSERT INTO analysis_file_mapping (analysis_id, file_id, file_type, created_at)
SELECT analysis_id, id, file_type, created_at
FROM analysis_files
WHERE analysis_id IS NOT NULL;

-- 3. Create indexes for better query performance
CREATE INDEX idx_analysis_file_mapping_analysis_id ON analysis_file_mapping(analysis_id);
CREATE INDEX idx_analysis_file_mapping_file_id ON analysis_file_mapping(file_id);
CREATE INDEX idx_analysis_file_mapping_type ON analysis_file_mapping(file_type);
CREATE INDEX idx_analysis_file_mapping_created_at ON analysis_file_mapping(created_at);

-- 4. Remove the analysis_id column from analysis_files table
-- Note: This is a breaking change, ensure all code is updated first
ALTER TABLE analysis_files DROP CONSTRAINT IF EXISTS analysis_files_analysis_id_fkey;
ALTER TABLE analysis_files DROP COLUMN IF EXISTS analysis_id;

-- 5. Drop the old index on analysis_id (if it still exists)
DROP INDEX IF EXISTS idx_analysis_files_analysis_id;
