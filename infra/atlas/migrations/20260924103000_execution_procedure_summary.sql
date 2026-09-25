-- Execution's procedure summary: one row per routine this system composed.
--
-- Maintained by the same background worker, and derived in the same strict
-- sense as its siblings: every column is recomputable from the `events`
-- table, so dropping the table and resetting the bookmark below to zero
-- rebuilds it exactly.
--
-- It exists because a fold cannot say which procedure is called
-- `tomography`. Answering that means knowing which stream to fold, which is
-- the question.

-- ---------------------------------------------------------------------------
-- proj_execution_procedure_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string, for the reason the run summary's migration gives.
--
-- `step_count` and not the steps. A procedure may hold a thousand of them, so
-- a page of fifty procedures would be almost entirely steps. How long the
-- routine is answers what a list is for; a caller that wants the steps reads
-- the procedure by id.
--
-- A count rather than the set of indices the walk summary holds, and the
-- difference is not inconsistency. A walk's progress is accumulated one step
-- report at a time, so an increment would double-count under at-least-once
-- delivery. This number is read whole off a single genesis payload, and every
-- redelivery of that row carries the same value.
--
-- One timestamp, like the plan summary and for the same reason. A procedure
-- has exactly one event, so a second column could never differ from the first
-- and would invite a reader to believe a lifecycle is being tracked.

CREATE TABLE proj_execution_procedure_summary (
    procedure_id uuid        PRIMARY KEY,
    name         text        NOT NULL,
    step_count   integer     NOT NULL,
    created_at   timestamptz NOT NULL
);

-- The lookup a caller makes when it holds a name and needs the routine.
--
-- NOT unique. Two procedures may share a name for the reason two plans may:
-- one routine composed two ways is two procedures, and which one an execution
-- cites is what says how it was composed. A unique index would make the
-- second invisible to every listing while it sat in the log.
CREATE INDEX proj_execution_procedure_summary_name_idx
    ON proj_execution_procedure_summary (name);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_procedure_summary_keyset_idx
    ON proj_execution_procedure_summary (created_at DESC, procedure_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_procedure_summary TO keeper_app;

-- Starting at zero so enabling this projection replays every procedure
-- already defined, which is what fills the table for a deployment older than
-- it.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_procedure_summary')
ON CONFLICT DO NOTHING;
