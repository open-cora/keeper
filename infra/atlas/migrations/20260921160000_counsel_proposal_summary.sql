-- Counsel's proposal summary: one row per run somebody put forward.
--
-- Maintained by a background worker tailing the event log. Derived data in
-- the strict sense: every column can be recomputed from the `events` table,
-- so dropping the table and resetting the bookmark below to zero rebuilds it
-- exactly. The log is the record; this is a convenience over it.
--
-- It exists because the one question this bounded context is for cannot be
-- answered by folding. "What is still open" names no proposal, and a fold has
-- to know which stream to fold.

-- ---------------------------------------------------------------------------
-- proj_counsel_proposal_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- The parameters are the one column of the aggregate that is not here. They
-- are unbounded, and a page of fifty rows would be mostly parameters, which
-- is the same call the run summary makes. Everything else is an id or a time.
--
-- `run_id` is nullable, and the null IS the status. There is no `is_open`
-- column beside it, because one bit spelled two ways is a pair of columns a
-- projection can write inconsistently, and the read side filters on the null
-- test for the same reason.
--
-- Two timestamps from two authorities, which is R8 reaching the read side.
-- `created_at` is when the proposal was made, and can only ever be this
-- system's own clock reading, because making one is an act performed here.
-- `taken_at` is when a run took it, and may be a caller's claim, because the
-- run started in an engine at a moment nothing here was present for.
--
-- `taken_at` is nullable for the same reason `run_id` is, and the two are
-- written by one statement so they cannot disagree about whether a proposal
-- was taken.

CREATE TABLE proj_counsel_proposal_summary (
    proposal_id uuid        PRIMARY KEY,
    actor_id    uuid        NOT NULL,
    plan_id     uuid        NOT NULL,
    run_id      uuid,
    created_at  timestamptz NOT NULL,
    taken_at    timestamptz
);

-- The lookup this context exists for: which proposals nobody acted on.
--
-- Partial, because the query it serves only ever asks for the null side, and
-- a partial index is smaller and stops being written to the moment a proposal
-- is taken. The complementary query, the ones a run did take, is served by
-- the keyset index below: it is expected to match most rows as a deployment
-- ages, and an index over most of a table earns less than a scan.
CREATE INDEX proj_counsel_proposal_summary_open_idx
    ON proj_counsel_proposal_summary (created_at DESC, proposal_id DESC)
    WHERE run_id IS NULL;

-- The keyset-pagination sort key. `proposal_id` is in it rather than only in
-- the output because two proposals made at the same instant have no defined
-- order between them otherwise, and a page boundary landing inside such a tie
-- repeats a row or skips one.
--
-- That tie is likelier here than next door. A dataset's timestamp is a
-- caller's claim, so ties come from backfills; a proposal's is this system's
-- own clock, so an agent making several proposals in one turn can land them
-- inside a single tick.
CREATE INDEX proj_counsel_proposal_summary_keyset_idx
    ON proj_counsel_proposal_summary (created_at DESC, proposal_id DESC);

-- No index on the proposer and none on the plan, because nothing asks. An
-- agent holds the ids of its own proposals and an operator asking what nobody
-- acted on is asking the open question above. An index maintained for nobody
-- is a write cost with no reader.

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_counsel_proposal_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_counsel_proposal_summary')
ON CONFLICT DO NOTHING;
