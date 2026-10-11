-- Bootstrap for the AI Equity Research database.
-- Alembic owns the full schema; this file only installs required extensions
-- so a fresh container is ready for migrations.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
