-- The Plan aggregate is renamed Operation, and its read model follows.
--
-- Plan was bluesky's word: there a plan is a generator of messages, and this
-- system borrowed the noun for "a named routine an engine has plus the schema
-- a run of it must satisfy". Operation is what that record actually is, an
-- executable primitive with a parameter contract, and it says nothing about
-- who executes it. That matters at a beamline with no engine, where the
-- routine is reached by writing a record rather than by calling a name.
--
-- Nothing about the row's shape changes. The table, its column, its two
-- indexes and its bookmark are renamed and nothing is added or dropped, so
-- there is no replay: every row that exists is still correct under the new
-- name.
--
-- Renamed rather than rebuilt, and renamed now, because the word is in
-- storage rather than only in code. The stream type moves from Plan to
-- Operation in the same commit, and no deployment has rows under either.

ALTER TABLE proj_execution_plan_summary
    RENAME TO proj_execution_operation_summary;

ALTER TABLE proj_execution_operation_summary
    RENAME COLUMN plan_id TO operation_id;

-- The indexes carry the old name in their own, which nothing reads but which
-- would leave the table describing an aggregate that no longer exists to
-- anyone reading the schema.
ALTER INDEX proj_execution_plan_summary_name_idx
    RENAME TO proj_execution_operation_summary_name_idx;

ALTER INDEX proj_execution_plan_summary_keyset_idx
    RENAME TO proj_execution_operation_summary_keyset_idx;

-- A primary key keeps its own name when its table is renamed, so it is not
-- covered by the two above and the table would otherwise keep a constraint
-- named for the aggregate this migration exists to rename. Renaming the
-- constraint renames the index behind it.
ALTER TABLE proj_execution_operation_summary
    RENAME CONSTRAINT proj_execution_plan_summary_pkey
    TO proj_execution_operation_summary_pkey;

-- The bookmark is found by name, and the projection's registered name moves
-- with the table, so this row has to move with both or the worker advances a
-- cursor over rows it never wrote.
UPDATE projection_bookmarks
SET name = 'proj_execution_operation_summary'
WHERE name = 'proj_execution_plan_summary';

-- A deployment that never ran the old projection has no bookmark to rename,
-- so the row is seeded the way the original migration seeded it. Starting at
-- zero replays every operation already defined.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_operation_summary')
ON CONFLICT DO NOTHING;

-- Counsel's read model cites the same aggregate and carries the same column
-- name, so it moves in the same migration. A proposal names the operation it
-- proposes, and a row saying `plan_id` after the aggregate stopped being a
-- plan would be the one place in the schema still using the old word.
--
-- No index touches this column: the open lookup is a null test on
-- `execution_id` and the keyset carries `proposal_id`, so neither index name
-- nor definition mentions it.
ALTER TABLE proj_counsel_proposal_summary
    RENAME COLUMN plan_id TO operation_id;

-- No GRANT anywhere here. Postgres carries a table's privileges across a
-- rename, so the grants the original migrations made still hold.
