-- Execution's walk summary: one row per traversal of a procedure.
--
-- Maintained by a background worker tailing the event log. Derived data in
-- the strict sense: every column can be recomputed from the `events` table,
-- so dropping the table and resetting the bookmark below to zero rebuilds it
-- exactly. The log is the record; this is a convenience over it.
--
-- It exists for the one question folding cannot answer. A driver that
-- restarts holds the reference it minted and no walk id, and a fold has to
-- know which stream to fold.

-- ---------------------------------------------------------------------------
-- proj_execution_walk_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- The step list is not here. It is the largest thing a walk carries, up to a
-- thousand entries, and a page of fifty walks would be almost entirely steps.
-- What a list needs is how far the walk got, and a caller wanting the steps
-- has the id and one more call.
--
-- `reported_indices` is an array rather than a counter, and this is the one
-- place this table differs in kind from its siblings. Delivery into a
-- projection is at-least-once, so a replayed batch must leave the row where
-- the first pass left it. Every other projection here satisfies that by
-- writing absolute values; a count of steps is not one. An increment would
-- count a replayed step twice and report a walk further along than it is,
-- which is the one lie a record of an abandoned walk must not tell. A union
-- into a set is idempotent, so the row holds the set and the count a caller
-- reads is its size.
--
-- `step_count` is stored rather than derived because the list it counts is
-- not in this table. It cannot change: no command adds a step to a walk.
--
-- `ended` is a boolean rather than a status, matching the aggregate. A walk
-- has two states today, and the third arrives only when something can say a
-- walk was abandoned, which needs something watching rather than a column.
--
-- Two timestamps, both a caller's claim. Unlike a device's registration, a
-- walk is never an act this system performed: it began at a beamline and
-- every step ended there, so both columns carry what the driver reported.

CREATE TABLE proj_execution_walk_summary (
    walk_id          uuid        PRIMARY KEY,
    reference_scheme text        NOT NULL,
    reference_value  text        NOT NULL,
    procedure_name   text        NOT NULL,
    step_count       integer     NOT NULL,
    reported_indices integer[]   NOT NULL DEFAULT '{}',
    ended            boolean     NOT NULL DEFAULT false,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

-- The lookup a driver cannot work without: the reference it minted, to the id
-- this system assigned.
--
-- Not unique, and deliberately. Nothing on the write side stops two walks
-- carrying one reference, because an event sourced aggregate has no
-- consistency boundary spanning its siblings, so a unique index here would
-- fail the projection rather than the report and wedge the worker over a row
-- it can never write. The read side returns both and lets the caller see the
-- duplicate.
CREATE INDEX proj_execution_walk_summary_reference_idx
    ON proj_execution_walk_summary (reference_scheme, reference_value);

-- The keyset-pagination sort key. `walk_id` is in it rather than only in the
-- output because two walks reported at the same instant have no defined order
-- between them otherwise, and a page boundary landing inside such a tie
-- repeats a row or skips one.
CREATE INDEX proj_execution_walk_summary_keyset_idx
    ON proj_execution_walk_summary (created_at DESC, walk_id DESC);

-- No index on `ended` or on the progress pair. Nothing filters on either yet,
-- and the question they would serve, which walks stopped reporting, needs a
-- clock rather than a predicate: a walk that is not ended and not complete is
-- indistinguishable from one still running until something decides how long
-- is too long. That decision is not made anywhere yet.

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_walk_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_walk_summary')
ON CONFLICT DO NOTHING;
