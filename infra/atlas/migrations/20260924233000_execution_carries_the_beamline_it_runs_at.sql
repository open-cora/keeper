-- An execution carries the beamline it was dispatched to.
--
-- Copied off the procedure at dispatch, and this column is the reason the copy
-- exists at all. The work intake asks for every dispatched execution at one
-- beamline, which is a filter over many rows: a reference to the procedure
-- cannot be followed per row, and a summary row has to be selectable by
-- itself.
--
-- That is a different thing from the copy this tree removed a few migrations
-- ago, when a step stopped carrying a plan id and started citing the composed
-- step it came from. That copy answered one consumer's one question about one
-- row, with the whole definition one hop away. This one is a routing key on a
-- page of rows.
--
-- The projections advance on independent bookmarks, which is the other reason
-- the value is on the event rather than read across from
-- `proj_execution_procedure_summary` here. The execution projection can run
-- ahead of the procedure one and would find nothing to join to.
--
-- Dropped and rebuilt rather than altered, for the reason the procedure
-- summary was one migration ago: the column is NOT NULL, no existing row could
-- supply a value, the table is derived, and the bookmark below starts at zero
-- so the worker recomputes every row from the log.

DROP TABLE IF EXISTS proj_execution_execution_summary;

CREATE TABLE proj_execution_execution_summary (
    execution_id     uuid        PRIMARY KEY,
    procedure_id     uuid        NOT NULL,
    procedure_name   text        NOT NULL,
    beamline         text        NOT NULL,
    step_count       integer     NOT NULL,
    reported_indices integer[]   NOT NULL DEFAULT '{}',
    status           text        NOT NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

-- The lookup a caller makes when it holds a procedure and wants to know how its
-- executions went. NOT unique: a routine composed once is run every time it
-- runs, and every one of those rows is wanted.
CREATE INDEX proj_execution_execution_summary_procedure_idx
    ON proj_execution_execution_summary (procedure_id);

-- The work intake's query, and the reason `beamline` is on this table.
--
-- Both columns together, in that order, because every intake request fixes the
-- beamline and then asks for one status. A conductor at 2-BM polling for
-- dispatched work must not scan the executions of three other beamlines to
-- find out it has nothing to do, and that is the one query in this system
-- expected to run continuously.
CREATE INDEX proj_execution_execution_summary_intake_idx
    ON proj_execution_execution_summary (beamline, status);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_execution_summary_keyset_idx
    ON proj_execution_execution_summary (created_at DESC, execution_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_execution_summary TO keeper_app;

-- Recreated, so the bookmark goes too and starts at zero.
DELETE FROM projection_bookmarks WHERE name = 'proj_execution_execution_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_execution_summary')
ON CONFLICT DO NOTHING;
