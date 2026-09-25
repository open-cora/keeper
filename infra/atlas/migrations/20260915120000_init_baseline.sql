-- Baseline schema: event store, idempotency, projection bookmarks, and the
-- application role.
--
-- The keeper is greenfield, so this is one migration expressing the final shape
-- rather than the incremental chain that shape was reached by elsewhere.
-- Everything after this is forward-only: a correction is a NEW migration, and
-- this file is never edited once it has been applied anywhere.

-- ---------------------------------------------------------------------------
-- events
-- ---------------------------------------------------------------------------
-- A single table backs every aggregate stream across every bounded context.
-- `position` is the global commit-order watermark; `(stream_type, stream_id,
-- version)` is the per-stream optimistic-concurrency key, and the UNIQUE
-- constraint on it is what makes a concurrent append fail rather than
-- interleave.
--
-- `transaction_id` exists because `position` alone is not safe to page on: a
-- bigserial is allocated before commit, so a reader tailing by position can
-- step over a row whose transaction has not committed yet and never come back
-- for it. Projections advance by `(transaction_id, position)` with an xmin
-- exclusion instead.
--
-- Routing is on `(stream_type, event_type)`, never `event_type` alone: the
-- column stores an unqualified class name, and a collision across bounded
-- contexts is plausible.

CREATE TABLE events (
    position        bigserial    PRIMARY KEY,
    event_id        uuid         NOT NULL,
    stream_type     text         NOT NULL,
    stream_id       uuid         NOT NULL,
    version         integer      NOT NULL CHECK (version > 0),
    event_type      text         NOT NULL,
    schema_version  integer      NOT NULL DEFAULT 1 CHECK (schema_version > 0),
    payload         jsonb        NOT NULL,
    metadata        jsonb        NOT NULL DEFAULT '{}'::jsonb,
    correlation_id  uuid         NOT NULL,
    causation_id    uuid,
    principal_id    uuid,
    transaction_id  xid8         NOT NULL DEFAULT pg_current_xact_id(),
    occurred_at     timestamptz  NOT NULL,
    recorded_at     timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT events_stream_version_unique
        UNIQUE (stream_type, stream_id, version)
);

-- `event_id` is the subscriber-side dedup key: delivery is at-least-once, so a
-- subscriber checkpoints on this rather than on position.
CREATE UNIQUE INDEX events_event_id_unique ON events (event_id);

-- Stream load (WHERE stream_type = $1 AND stream_id = $2 ORDER BY version) is
-- already served by the UNIQUE constraint's index.
CREATE INDEX events_correlation_idx ON events (correlation_id);
CREATE INDEX events_recorded_at_idx ON events (recorded_at);
CREATE INDEX events_advance_idx ON events (transaction_id, position);

-- Wake-up signal for subscribers. Best-effort and NON-DURABLE: a listener that
-- is not connected at INSERT time never learns of the row, so every subscriber
-- must also poll from a persisted watermark. The payload is deliberately small;
-- it is a hint to poll now, not the event itself.
CREATE OR REPLACE FUNCTION events_notify() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'events',
        json_build_object(
            'position',    NEW.position,
            'stream_type', NEW.stream_type,
            'stream_id',   NEW.stream_id,
            'event_type',  NEW.event_type
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER events_notify_trigger
    AFTER INSERT ON events
    FOR EACH ROW
    EXECUTE FUNCTION events_notify();

-- ---------------------------------------------------------------------------
-- idempotency_keys
-- ---------------------------------------------------------------------------
-- The cache namespace is the composite (principal_id, key, surface_id), per
-- IETF draft-ietf-httpapi-idempotency-key-header section 5. surface_id is in
-- the key so the same Idempotency-Key cannot collide across the REST and MCP
-- surfaces. command_hash and command_name are conflict-detection fields, not
-- part of the namespace: a retry with the same key and a different body is a
-- 422, not a cache hit.

CREATE TABLE idempotency_keys (
    principal_id   uuid        NOT NULL,
    key            text        NOT NULL,
    surface_id     uuid        NOT NULL,
    command_hash   text        NOT NULL,
    command_name   text        NOT NULL,
    result         jsonb,
    locked_at      timestamptz,
    error_type     text,
    error_msg      text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (principal_id, key, surface_id),
    -- Exactly three legal states: in flight (locked, no outcome), succeeded
    -- (a result), or failed (an error). Anything else is a bug that would
    -- otherwise be discovered as a mis-served retry.
    CONSTRAINT idempotency_keys_state_chk CHECK (
        (locked_at IS NOT NULL AND result IS NULL AND error_type IS NULL)
        OR (locked_at IS NULL AND result IS NOT NULL AND error_type IS NULL)
        OR (
            locked_at IS NULL
            AND result IS NULL
            AND error_type IS NOT NULL
            AND error_msg IS NOT NULL
        )
    )
);

CREATE INDEX idempotency_keys_created_at_idx ON idempotency_keys (created_at);

-- ---------------------------------------------------------------------------
-- projection_bookmarks
-- ---------------------------------------------------------------------------
-- One durable cursor per projection or reaction. The observability columns are
-- here rather than in a log because a projection that is silently wedged looks
-- identical to one with nothing to do.

CREATE TABLE projection_bookmarks (
    name                   text        PRIMARY KEY,
    last_transaction_id    xid8        NOT NULL DEFAULT '0'::xid8,
    last_position          bigint      NOT NULL DEFAULT 0,
    last_event_recorded_at timestamptz,
    last_error_at          timestamptz,
    last_error_message     text,
    consecutive_failures   integer     NOT NULL DEFAULT 0,
    updated_at             timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- keeper_app role and grants
-- ---------------------------------------------------------------------------
-- The application connects as this role; migrations run as the database owner.
-- That split is what makes event immutability a database guarantee rather than
-- an application convention: even a compromised application cannot UPDATE or
-- DELETE an event, because the role it holds was never granted the privilege.

DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'keeper_app') THEN
        CREATE ROLE keeper_app WITH LOGIN PASSWORD 'keeper_app';
    END IF;
END
$do$;

GRANT USAGE ON SCHEMA public TO keeper_app;

GRANT SELECT, INSERT ON events TO keeper_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys TO keeper_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON projection_bookmarks TO keeper_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO keeper_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO keeper_app;

-- The append-only guarantee, stated as a revocation so it survives a future
-- blanket GRANT on the schema.
REVOKE UPDATE, DELETE, TRUNCATE ON events FROM keeper_app;
