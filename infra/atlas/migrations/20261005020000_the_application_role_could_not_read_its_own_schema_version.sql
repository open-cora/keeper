-- The boot gate reads a table the application role cannot see, so the role
-- the deployment was designed to use could never start.
--
-- `keeper_app` exists so the running server cannot rewrite history: it holds
-- SELECT and INSERT on `events` and the baseline revokes UPDATE, DELETE and
-- TRUNCATE. That makes append-only a database guarantee rather than a promise
-- about the application's own SQL.
--
-- The deployment does not use it. `infra/deploy/install.sh` points
-- DATABASE_URL at the schema owner, and the reason is here rather than in
-- anybody's judgement: switching it over fails at startup.
--
--     SELECT coalesce(max(version), '')
--     FROM atlas_schema_revisions.atlas_schema_revisions
--
-- is the first thing the process runs, because a server that booted against a
-- schema it does not expect would append history nobody can trust. Atlas
-- creates that schema while running as the owner, and nothing ever granted
-- the application role access to it, so the query raises
-- InsufficientPrivilege and the lifespan exits.
--
-- ## Why read access is enough, and why it is the right amount
--
-- The gate only asks which migration is applied. It never writes there, and
-- it must not: the revision table is Atlas's own bookkeeping, and an
-- application that could edit it could tell itself any schema was applied,
-- which is the one lie that would make the gate worse than absent.
--
-- So USAGE on the schema and SELECT on the one table. No INSERT, no UPDATE,
-- no DELETE, and the same REVOKE spelling the baseline uses on `events`, so a
-- later blanket GRANT does not quietly hand them back.
--
-- ## The ordering this has to survive
--
-- Atlas creates its revision table on first apply, which may be after this
-- migration runs against a database that has one already, or before it
-- against a fresh one. The grants below are written to tolerate both:
-- the schema is created if absent so the GRANT has a subject, and Atlas
-- adopts an existing schema rather than failing on it.
--
-- ALTER DEFAULT PRIVILEGES is scoped to the owner, because Atlas is what
-- creates objects in there and the owner is what Atlas runs as. Without it a
-- future Atlas version adding a second bookkeeping table would reintroduce
-- exactly this failure, silently, at the next restart.

CREATE SCHEMA IF NOT EXISTS atlas_schema_revisions;

GRANT USAGE ON SCHEMA atlas_schema_revisions TO keeper_app;

GRANT SELECT ON ALL TABLES IN SCHEMA atlas_schema_revisions TO keeper_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA atlas_schema_revisions
    GRANT SELECT ON TABLES TO keeper_app;

-- Stated as a revocation so it survives a future blanket GRANT, which is the
-- same reason the baseline revokes on `events` after granting.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON ALL TABLES IN SCHEMA atlas_schema_revisions FROM keeper_app;
