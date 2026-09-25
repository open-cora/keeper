-- A procedure says which beamline it was composed for.
--
-- The routing key for the work intake. The keeper dispatches an execution and
-- something at a beamline has to be able to ask for the ones it can drive,
-- which means the question "every dispatched execution at 2-bm" has to be
-- answerable by a query rather than by reading each procedure in turn.
--
-- A procedure whose steps name `2bmb:m1` can only run at 2-BM, so this states
-- once what the device addresses in its steps already imply. It is asserted
-- rather than derived: parsing the prefix would mean this system owning a
-- grammar that belongs to whatever drives the procedure, which
-- `procedure/state.py` refuses for scopes and refuses here for the same
-- reason.
--
-- ## Dropped and rebuilt rather than altered
--
-- The column is NOT NULL and no existing row could supply a value, so an
-- ALTER would need a default that means nothing. This table is derived, the
-- events it is derived from are all still in the log, and the bookmark below
-- starts at zero, so the worker recomputes every row from the genesis events
-- on its next pass. That is the pattern every projection change in this tree
-- has used and the reason projections are safe to reshape at all.
--
-- The event payloads are a different matter. `ProcedureDefined` now carries
-- `beamline` and a row written before it does not, so a procedure defined
-- earlier fails to load rather than folding without one. That is stated in
-- `procedure/events.py` alongside the same note about step ids, and it is
-- acceptable for the same reason: nothing is deployed and no procedure in any
-- database anybody keeps was ever published.

DROP TABLE IF EXISTS proj_execution_procedure_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_procedure_summary (
    procedure_id uuid        PRIMARY KEY,
    name         text        NOT NULL,
    beamline     text        NOT NULL,
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

-- No index on `beamline`. Nothing filters procedures by it: the intake asks
-- about executions, and the column an intake query needs is the copy that
-- lands on `proj_execution_execution_summary`. This column exists so a listing
-- can show where a routine runs, which is a read of rows already selected.

-- Recreated, so the bookmark goes too and starts at zero. The worker raises on
-- a registered projection with no bookmark, and replaying from the start is
-- what refills the table.
DELETE FROM projection_bookmarks WHERE name = 'proj_execution_procedure_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_procedure_summary')
ON CONFLICT DO NOTHING;
