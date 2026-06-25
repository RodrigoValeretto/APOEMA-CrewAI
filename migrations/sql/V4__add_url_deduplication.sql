-- Add URL-based deduplication for downloaded files
-- This allows reuse of files downloaded from the same URL

-- 1. Remove the content_hash column (unused, replaced by URL tracking)
ALTER TABLE analysis_files DROP COLUMN IF EXISTS content_hash;

-- 2. Add url column for tracking download sources
ALTER TABLE analysis_files ADD COLUMN url VARCHAR(512) DEFAULT NULL;

-- 3. Create unique index on url to ensure one file per unique URL
-- Only indexes non-NULL values to allow multiple files without URLs (uploaded files)
CREATE UNIQUE INDEX idx_analysis_files_url ON analysis_files(url) WHERE url IS NOT NULL;
