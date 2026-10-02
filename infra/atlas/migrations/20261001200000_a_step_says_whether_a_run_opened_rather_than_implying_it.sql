-- Separate "a run opened on this step" from "the engine had a name for it".
--
-- The table answered the first question by asking the second: a row with an
-- `engine_reference` was a step that opened a run, because the only writer of
-- that column was the driver's own step report and a driver only held a
-- reference when its call had opened one.
--
-- Both halves of that have stopped being true.
--
-- The driver gave the column up, because driving a step cannot tell you what
-- the engine called the run. The value it held was whatever its call returned,
-- which is proximity rather than knowledge, and the same value is readable by
-- anything watching the engine. So the reference now arrives on
-- `ExecutionStepEngineStarted`, from whatever watched the run, and
-- `ExecutionStepDone` no longer carries it into the row.
--
-- And a reference is now optional in a way it was not. It is the engine's own
-- identifier for a run rather than a path that happened to be to hand, and not
-- every engine publishes one: of the stations this serves, two do and the rest
-- do not. A run at one of the others opened, ended and produced data, and would
-- have been invisible to a question that reads a null reference as "no run".
--
-- So the fact gets its own column. `run_opened_at` says a run opened and when a
-- watcher saw it, `engine_reference` says what that run is called and is null
-- wherever nobody can say, and the gap this table exists to surface stops
-- depending on the second to answer the first.
--
-- `reported_at IS NOT NULL` joins the filter at the same time, and for a
-- reason the old shape hid. A run used to enter this table already finished,
-- because the one event that filled the reference was the ending. A run now
-- enters it when it begins, so without that clause every scan currently
-- running would read as a run whose data nobody recorded.

ALTER TABLE proj_execution_step_summary
    ADD COLUMN run_opened_at timestamptz;

DROP INDEX proj_execution_step_summary_unfiled_idx;

-- The question this table was added for: runs whose data nothing recorded.
-- Partial, because the rows that satisfy it are a small minority of a table
-- holding every step of every execution, and a full index would be mostly
-- rows no caller of this query ever reads.
CREATE INDEX proj_execution_step_summary_unfiled_idx
    ON proj_execution_step_summary (reported_at DESC, step_id DESC)
    WHERE run_opened_at IS NOT NULL AND reported_at IS NOT NULL AND dataset_id IS NULL;

-- Derived, so rebuilt rather than backfilled. Every row's reference was
-- written by an arm that no longer writes it, and no row has ever had a
-- `run_opened_at`, so the only honest version of this table is the one the
-- worker's next pass builds from the log.
UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_execution_step_summary';
