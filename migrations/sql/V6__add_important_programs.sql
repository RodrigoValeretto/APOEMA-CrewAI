-- Add important programs column to analysis table
-- Program identifiers (Sigla values from the plot CSV) that the user marked as
-- important; the plots highlight them and the AI insights must consider them.
-- Stored as a text array so retries/re-runs keep the same highlights.
ALTER TABLE analysis ADD COLUMN IF NOT EXISTS important_programs TEXT[];
