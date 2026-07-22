-- Runs automatically on first container start (mounted into
-- /docker-entrypoint-initdb.d/ by docker-compose). Postgres only executes
-- these scripts when the data directory is empty, so it does not re-run on
-- every restart.
--
-- Table creation/columns are owned by Alembic migrations (backend/alembic),
-- run automatically by the backend container's entrypoint.sh on startup.
-- This script only sets up database-level prerequisites that migrations
-- assume are already in place.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Sanity check row so `docker compose logs db` shows init ran.
DO $$
BEGIN
    RAISE NOTICE 'agentic-mvp: database initialization complete for %', current_database();
END $$;
