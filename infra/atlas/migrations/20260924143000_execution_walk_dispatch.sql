-- Reshape the walk summary for a dispatched walk rather than a reported one.
--
-- The walk aggregate changed posture. Its genesis was `WalkReported`, meaning
-- something drove a procedure elsewhere and told this system afterwards; it is
-- now `WalkDispatched`, meaning this system handed the procedure out. Three
-- columns follow from that.
--
--   reference_scheme, reference_value  ->  dropped
--   procedure_id                       ->  added
--   ended boolean                      ->  status text
--
-- A driver used to mint a name for the walk before its first step, because at
-- that moment there was no handle. Under a dispatch there is: this system
-- creates the record first, so the walk id is the handle and a second name
-- would be a second thing to keep in step.
--
-- `status` replaces `ended` because a dispatched walk has more than two states
-- to be in. It can be waiting for something to take it up, which is the first
-- genuine transient in this schema and the one a reader most needs to see: a
-- row sitting at 'Dispatched' with an old created_at says nothing ever picked
-- the work up, which is a different failure from a driver that died partway.
--
-- This table is derived, so it is dropped and rebuilt from the log rather than
-- migrated in place. Note what that does NOT recover: walk streams written
-- under the previous shape carry `WalkReported` rows, which this version of
-- the code cannot deserialize, so a replay over them fails rather than
-- producing rows. No deployment holds such data. The aggregate landed in this
-- same series of changes and nothing is published.

DROP TABLE IF EXISTS proj_execution_walk_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

CREATE TABLE proj_execution_walk_summary (
    walk_id          uuid        PRIMARY KEY,
    procedure_id     uuid        NOT NULL,
    procedure_name   text        NOT NULL,
    step_count       integer     NOT NULL,
    reported_indices integer[]   NOT NULL DEFAULT '{}',
    status           text        NOT NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL
);

-- `reported_indices` holds the set of steps reported, not a count, because a
-- counter cannot be made idempotent under at-least-once delivery: a replayed
-- batch would increment twice and report a walk further along than it is. A
-- union is idempotent where an increment is not, and the number a caller reads
-- is the cardinality.

-- The lookup a caller makes when it holds a procedure and wants to know how
-- its walks went. NOT unique: a routine composed once is walked every time it
-- runs, and every one of those rows is wanted.
CREATE INDEX proj_execution_walk_summary_procedure_idx
    ON proj_execution_walk_summary (procedure_id);

-- The keyset-pagination sort key, with the id in it for the same tie-breaking
-- reason its siblings carry one.
CREATE INDEX proj_execution_walk_summary_keyset_idx
    ON proj_execution_walk_summary (created_at DESC, walk_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_walk_summary TO keeper_app;

-- Rewind the bookmark so the rebuilt table fills from the log rather than
-- starting empty at whatever position the old one had reached.
UPDATE projection_bookmarks
SET last_position = 0, last_transaction_id = '0'::xid8
WHERE name = 'proj_execution_walk_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_walk_summary')
ON CONFLICT DO NOTHING;
