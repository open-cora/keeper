-- A proposal stops pointing at a run and points at one acquisition instead.
--
--   run_id  ->  execution_id + step_id
--
-- The same move a dataset made one migration earlier, for a different reason.
-- A dataset needed the step because an execution writes data several times and
-- a reference to the traversal would lose which acquisition produced what. A
-- proposal needs it because a run is no longer a record this system keeps: what
-- was proposed is now run by one step of a procedure this system composed, and
-- that step is the only thing there is to point at.
--
-- Both ids and not the step alone, which is the rule this tree now follows
-- wherever a step is named. A step is an entity inside the Execution aggregate
-- rather than a stream of its own, so the root is what makes it findable and
-- checkable, and the root comes first.
--
-- `execution_id` is what the open filter tests, and the column the partial
-- index below is built on. Either would serve: the two are written by one
-- statement from one event, so a row holding one without the other is not a row
-- this projection can produce. The root is named because it is the one a reader
-- can follow on its own.
--
-- There is no index on the step, unlike next door. Custody indexes it because
-- the question there is which data one acquisition produced, and a proposal is
-- reached from the proposal side: an agent holds the id of what it put forward.
--
-- Derived, so dropped and rebuilt from the log rather than migrated in place.
-- Rows written under the old shape carry `run_id` in their payload and this
-- version of the projection reads `execution_id`, so a replay over them fails
-- rather than producing rows. No deployment holds such data.

DROP TABLE IF EXISTS proj_counsel_proposal_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_counsel_proposal_summary (
    proposal_id  uuid        PRIMARY KEY,
    actor_id     uuid        NOT NULL,
    plan_id      uuid        NOT NULL,
    execution_id uuid,
    step_id      uuid,
    created_at   timestamptz NOT NULL,
    taken_at     timestamptz
);

-- The lookup this context exists for: which proposals nobody acted on.
--
-- Partial, because the query it serves only ever asks for the null side, and
-- a partial index is smaller and stops being written to the moment a proposal
-- is taken. The complementary query, the ones an acquisition did take, is
-- served by the keyset index below: it is expected to match most rows as a
-- deployment ages, and an index over most of a table earns less than a scan.
CREATE INDEX proj_counsel_proposal_summary_open_idx
    ON proj_counsel_proposal_summary (created_at DESC, proposal_id DESC)
    WHERE execution_id IS NULL;

-- The keyset-pagination sort key. `proposal_id` is in it rather than only in
-- the output because two proposals made at the same instant have no defined
-- order between them otherwise, and a page boundary landing inside such a tie
-- repeats a row or skips one.
CREATE INDEX proj_counsel_proposal_summary_keyset_idx
    ON proj_counsel_proposal_summary (created_at DESC, proposal_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_counsel_proposal_summary TO keeper_app;

UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_counsel_proposal_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_counsel_proposal_summary')
ON CONFLICT DO NOTHING;
