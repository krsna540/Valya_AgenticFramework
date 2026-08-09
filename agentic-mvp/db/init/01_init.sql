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

-- MLflow's tracking-server tables (experiments/runs/metrics/...) live in
-- their own schema rather than `public`, so they never risk colliding by
-- name with an Alembic-managed app table — see docker-compose.yml's
-- `mlflow` service, which points its --backend-store-uri at this schema
-- via `?options=-csearch_path=mlflow`. MLflow creates its own tables
-- inside it on first boot; this script only needs the schema to exist.
CREATE SCHEMA IF NOT EXISTS mlflow;

-- Sanity check row so `docker compose logs db` shows init ran.
DO $$
BEGIN
    RAISE NOTICE 'agentic-mvp: database initialization complete for %', current_database();
END $$;
