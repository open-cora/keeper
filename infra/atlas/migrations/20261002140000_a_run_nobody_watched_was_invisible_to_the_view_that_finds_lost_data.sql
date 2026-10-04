-- Ask the procedure whether a step should have produced data, not the watcher.
--
-- The filter gated on `run_opened_at`, which is written by
-- `ExecutionStepEngineStarted` and therefore only ever by a reporter. So the
-- view could see a run a watcher saw open and that recorded nothing, and could
-- not see a run nobody watched at all. The second is the worse failure of the
-- two: the first loses one run's address, the second loses every run at a
-- beamline and says nothing.
--
-- Measured at 19-BM rather than reasoned about. With the reporter stopped, a
-- scan walked to Done, wrote /local1/corasim19bm/cora-simulated-proposal/
-- scan_029.h5 under ScanUUID 0cb2f7c6-fdba-4107-8bf4-8b02901d3459, registered
-- no dataset, and never appeared in this listing. Restarting the reporter did
-- not recover it, because a record source acts on transitions and that one was
-- over. The prose in docs/responsibilities.md claimed the opposite.
--
-- The question the view wants is whether driving this step opens a run, and
-- that is a property of the procedure it was dispatched from. The keeper
-- composed the execution and knew the answer before any client was involved;
-- it simply had nowhere to put it. `run_opened_at` was standing in for it, and
-- the two agreed only while every beamline had a reporter.
--
-- So the kind gets carried. `ProcedureDefined` already distinguishes its two
-- step classes on the wire, the dispatched step already names the composed
-- step it came from, and the projection now folds the first to answer for the
-- second. Nothing is added to an event, which matters for the replay below:
-- an old execution gets its answer from the procedure it cites, exactly as a
-- new one does.
--
-- `run_opened_at` stays, demoted from gate to attribute, because the two
-- failures want different people. A run watched and empty is a filing or
-- engine fault; a run with no watcher is a deployment fault. Returning the
-- column lets a reader tell them apart instead of seeing one list.
--
-- The outcome clause is new and is not a refinement either. Skipped and
-- Refused were excluded for free while the gate was `run_opened_at`, because
-- nothing opened on a step that never ran. Gating on the definition instead
-- admits them, so they are excluded on purpose.

CREATE TABLE proj_execution_step_summary_kinds (
    procedure_step_id uuid    PRIMARY KEY,
    opens_a_run       boolean NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_step_summary_kinds TO keeper_app;

ALTER TABLE proj_execution_step_summary
    ADD COLUMN opens_a_run boolean;

DROP INDEX proj_execution_step_summary_unfiled_idx;

-- The question this table was added for: runs whose data nothing recorded.
-- Partial, because the rows that satisfy it are a small minority of a table
-- holding every step of every execution, and a full index would be mostly
-- rows no caller of this query ever reads.
CREATE INDEX proj_execution_step_summary_unfiled_idx
    ON proj_execution_step_summary (reported_at DESC, step_id DESC)
    WHERE opens_a_run
      AND reported_at IS NOT NULL
      AND outcome IN ('Done', 'Broken')
      AND dataset_id IS NULL;

-- Truncated and not only reset, which is the rule this directory learned one
-- migration ago. A replay runs an insert taking ON CONFLICT DO NOTHING and a
-- set of updates, and neither writes a column that was null on a row already
-- there. Every existing row would keep `opens_a_run` null, the filter would
-- match nothing, and the listing would come back empty while reading as
-- rebuilt. A reset pairs with a truncate whenever a change adds a column the
-- genesis arm fills.
TRUNCATE TABLE proj_execution_step_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log
TRUNCATE TABLE proj_execution_step_summary_kinds;  -- atlas:safety:allow=projection table, rebuilt from the event log

UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_execution_step_summary';
