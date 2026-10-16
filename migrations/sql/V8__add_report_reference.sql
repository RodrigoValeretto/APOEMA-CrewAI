-- V8: report-reference — groups analyses that belong to the same report.
-- A report is composed of several images; each image is analyzed separately
-- (one analysis per image) but all share the same report_reference so they
-- can be fetched and related back to the report afterwards.
ALTER TABLE analysis ADD COLUMN IF NOT EXISTS report_reference VARCHAR(255);
CREATE INDEX IF NOT EXISTS idx_analysis_report_reference ON analysis(report_reference);
