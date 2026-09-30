-- One row per step, so the record can be asked what a step produced and
-- whether anybody wrote down where it went.
--
-- The tree had no step-level read model at all. An execution summary carries
-- how far a traversal got and deliberately drops the steps, because a page of
-- fifty executions would otherwise be almost entirely steps. That leaves
-- "which steps did this execution run, and what came out of each" answerable
-- only by folding the stream, and "which runs produced data nobody recorded"
-- answerable not at all.
--
-- ## Why this table spans two bounded contexts
--
-- `dataset_id` is Custody's fact and every other column is Execution's. The
-- projection subscribes to `DatasetRegistered` to fill it.
--
-- An aggregate may not reach across that line and this does not: Execution's
-- write side learns nothing, and no decider, evolver or command here can see
-- a dataset. What spans the two is a read model, which is the one thing that
-- is allowed to, because it is derived and can be dropped and rebuilt from
-- the log at any time.
--
-- The direction was forced rather than chosen. `ExecutionStepDone` names its
-- step by index and `DatasetRegistered` names it by id, so only
-- `ExecutionDispatched` can pair the two, and whatever holds this has to
-- subscribe to all three. Custody has no aggregate a step row could hang
-- from, and inventing one would put Execution's identities behind a second
-- context's public surface.
--
-- ## Why a row exists for every step
--
-- Including the ones that produce nothing. Which steps will open a run is not
-- knowable at dispatch: a dispatched step carries its sentence and the
-- operation it cites, and nothing that separates a move from an acquisition.
-- So the genesis arm writes them all and the later arms fill in what
-- happened, which is the same shape the execution summary uses and needs no
-- arm that deletes.
--
-- A step that produced nothing is then simply a row with no
-- `engine_reference`, and the gap this exists to surface is
-- `engine_reference IS NOT NULL AND dataset_id IS NULL`.
--
-- Derived, so created rather than migrated, and rebuilt from the log by the
-- worker's first pass.

CREATE TABLE proj_execution_step_summary (
    step_id          uuid        PRIMARY KEY,
    execution_id     uuid        NOT NULL,
    step_index       integer     NOT NULL,
    describes        text        NOT NULL,
    beamline         text        NOT NULL,
    outcome          text,
    engine_reference text,
    reported_at      timestamptz,
    dataset_id       uuid,
    filed_at         timestamptz,
    created_at       timestamptz NOT NULL
);

-- The steps of one execution, in the order the dispatch fixed.
CREATE UNIQUE INDEX proj_execution_step_summary_execution_idx
    ON proj_execution_step_summary (execution_id, step_index);

-- The question this table was added for: runs whose data nothing recorded.
-- Partial, because the rows that satisfy it are a small minority of a table
-- holding every step of every execution, and a full index would be mostly
-- rows no caller of this query ever reads.
CREATE INDEX proj_execution_step_summary_unfiled_idx
    ON proj_execution_step_summary (reported_at DESC, step_id DESC)
    WHERE engine_reference IS NOT NULL AND dataset_id IS NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_step_summary TO keeper_app;

UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_execution_step_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_step_summary')
ON CONFLICT DO NOTHING;
