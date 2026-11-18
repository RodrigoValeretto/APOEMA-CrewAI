-- V10: result_json — store the parsed JSON object of a task result separately.
-- When a task returns a JSON object, the object is stored in `result_json`
-- (JSONB) and the raw `result` text is set to NULL. `result` must therefore
-- allow NULL.
ALTER TABLE analysis_results ADD COLUMN IF NOT EXISTS result_json JSONB;
ALTER TABLE analysis_results ALTER COLUMN result DROP NOT NULL;
