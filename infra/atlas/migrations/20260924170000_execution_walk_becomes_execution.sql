-- The Walk aggregate becomes Execution, and its summary table follows.
--
-- The rename is not cosmetic. A walk was one traversal of a procedure as
-- reported by whatever drove it; an execution is one this system dispatched.
-- The aggregate had already changed posture, and `Walk` was the last place the
-- old one was still being asserted.
--
--   proj_execution_walk_summary  ->  proj_execution_execution_summary
--   stream_type 'Walk'           ->  'Execution'
--
-- The table name stutters, and that is the convention holding rather than
-- breaking. Every projection here is `proj_<context>_<aggregate>_summary`, and
-- an aggregate whose name matches its context produces the name twice. Dropping
-- one would make this table the only one a reader cannot derive, and
-- `proj_execution_summary` would read as the context's summary rather than this
-- aggregate's, which is wrong beside the plan, procedure and run tables.
--
-- ---------------------------------------------------------------------------
-- What this does not recover
-- ---------------------------------------------------------------------------
-- Rows in `events` filed under stream_type 'Walk' are not rewritten. The events
-- table is append-only and rewriting history to make a rename tidy is the one
-- edit this system does not make. Those rows stay, unreadable: no loader asks
-- for that stream type any more, and the classes their payloads name are gone.
--
-- `test_stream_types_are_pinned.py` keeps 'Walk' in a retired set for exactly
-- this reason, so the record of what the orphaned rows are called survives the
-- code that wrote them.
--
-- No deployment holds such rows. The aggregate was added and renamed inside one
-- series of changes and nothing is published.

DROP TABLE IF EXISTS proj_execution_walk_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_execution_summary (
    execution_id     uuid        PRIMARY KEY,
    procedure_id     uuid        NOT NULL,
    procedure_name   text        NOT NULL,
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

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_execution_summary_keyset_idx
    ON proj_execution_execution_summary (created_at DESC, execution_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_execution_summary TO keeper_app;

-- The old bookmark names a projection nothing registers now.
DELETE FROM projection_bookmarks WHERE name = 'proj_execution_walk_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_execution_summary')
ON CONFLICT DO NOTHING;
