-- Add model column to analysis table
-- Allows the retry endpoint to re-queue a failed analysis with the same model
ALTER TABLE analysis ADD COLUMN IF NOT EXISTS model VARCHAR(50);
