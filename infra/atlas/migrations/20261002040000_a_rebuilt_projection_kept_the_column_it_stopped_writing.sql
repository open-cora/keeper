-- Empty the step summary before rebuilding it, rather than only rewinding.
--
-- The migration before this one moved `engine_reference` from the driver's
-- step report to the watcher's run-opened event, and reset the projection
-- bookmark so the table would be rebuilt. Its own prose claimed that made the
-- table "the only honest version", and that was wrong.
--
-- A rebuild here is a replay, and the arms a replay runs are an insert that
-- takes ON CONFLICT DO NOTHING and a set of updates. Neither can clear a
-- column. So every value the retired arm had written stayed exactly where it
-- was, and no current arm would ever write over it or null it.
--
-- Measured after the deploy: of 41 rows, 3 carried the identifier a watcher
-- reported and 26 still carried a filesystem path that the driver's report
-- had put there. A path is not what an engine calls a run, which is the whole
-- reason that arm was retired, so those 26 rows were making a claim this
-- system no longer makes anywhere else.
--
-- Nothing read them. The gap listing moved to `run_opened_at` in the same
-- change and was correct throughout. They were visible on the step of any
-- execution anybody fetched, which is quieter and no less wrong.
--
-- ## Why this is the table's problem and not that migration's
--
-- Every bookmark reset in this directory relies on a replay to produce the
-- current answer, and until now every one of them was safe, because every
-- column still had an arm writing it. The first change to retire an arm is
-- the first to find that a replay cannot undo what a retired arm wrote.
--
-- A projection is derived and can be dropped, so the version that owes
-- nothing to the code that filled it is the one built from empty. That is
-- what this does, and it is what a bookmark reset should be paired with
-- whenever a change stops writing something.

TRUNCATE TABLE proj_execution_step_summary;

UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_execution_step_summary';
