-- A dataset stops pointing at a run and points at one acquisition instead.
--
--   run_id  ->  execution_id + step_id
--
-- An execution may hold a thousand steps and acquire several times, and each
-- acquisition writes its own data. A reference to the execution alone would say
-- that these five datasets came out of this traversal and nothing about which
-- came from where, which at a tomography beamline is the sample position: the
-- one thing that makes the data interpretable.
--
-- Both ids and not the step alone. A step id is unique and is enough to look a
-- step up; it is not enough to CHECK one. A step is an entity inside the
-- Execution aggregate rather than a stream of its own, so establishing that it
-- exists means loading the execution that holds it, and the registering handler
-- does exactly that. The root comes first and the step qualifies it, which is
-- the order every other cross-aggregate reference in this tree reads in.
--
-- The index moves with the reference. What a caller asks is which data one
-- acquisition produced, so the index is on the step. It is not unique: how many
-- datasets an acquisition writes is the reporting side's policy and not a rule
-- here.
--
-- Derived, so dropped and rebuilt from the log rather than migrated in place.
-- Rows written under the old shape carry `run_id` in their payload and this
-- version of the projection reads `execution_id`, so a replay over them fails
-- rather than producing rows. No deployment holds such data.

DROP TABLE IF EXISTS proj_custody_dataset_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_custody_dataset_summary (
    dataset_id          uuid        PRIMARY KEY,
    execution_id        uuid        NOT NULL,
    step_id             uuid        NOT NULL,
    external_ref_scheme text        NOT NULL,
    external_ref_value  text        NOT NULL,
    created_at          timestamptz NOT NULL
);

-- The lookup this context exists for: which data did this acquisition produce.
CREATE INDEX proj_custody_dataset_summary_step_idx
    ON proj_custody_dataset_summary (step_id);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_custody_dataset_summary_keyset_idx
    ON proj_custody_dataset_summary (created_at DESC, dataset_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_custody_dataset_summary TO keeper_app;

UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_custody_dataset_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_custody_dataset_summary')
ON CONFLICT DO NOTHING;
