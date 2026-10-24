-- =============================================================================
-- QueryPilot AI — Database Initialization
-- Runs against the default 'querypilot_app' database created by POSTGRES_DB env var
-- =============================================================================

-- Create the target database for analytics queries
CREATE DATABASE querypilot_target;

-- Create a read-only role for analytics queries (least privilege)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'target_readonly') THEN
        CREATE ROLE target_readonly WITH LOGIN PASSWORD 'target_readonly_dev';
    END IF;
END $$;

GRANT CONNECT ON DATABASE querypilot_target TO target_readonly;
