-- Execution's plan summary: the second projection table, and the smaller one.
--
-- One row per plan, maintained by the same background worker. Derived in the
-- same strict sense as the run summary: every column is recomputable from the
-- `events` table, so dropping the table and resetting the bookmark below to
-- zero rebuilds it exactly.
--
-- It exists because a fold cannot say which plan is called `count`. Answering
-- that means knowing which stream to fold, which is the question.

-- ---------------------------------------------------------------------------
-- proj_execution_plan_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string, for the reason the run summary's migration gives.
--
-- `parameters_schema` is deliberately absent. It is the largest thing a plan
-- carries and a page of fifty rows would be a page of schemas; a caller that
-- wants one reads the plan by id.
--
-- One timestamp, unlike the run summary's two, and here that is not a choice.
-- A plan has exactly one event. Nothing changes it, so a second column could
-- never differ from the first and would invite a reader to believe a
-- lifecycle is being tracked.

CREATE TABLE proj_execution_plan_summary (
    plan_id    uuid        PRIMARY KEY,
    name       text        NOT NULL,
    created_at timestamptz NOT NULL
);

-- The lookup an adapter makes: it holds the name an engine calls a routine
-- and needs the plan that name was written down as.
--
-- NOT unique, and here the aggregate insists on it rather than merely
-- permitting it. Two plans may share a name on purpose: one routine
-- constrained two ways is two plans, and which one a run cites is what says
-- how it was constrained. A unique index would make the second invisible,
-- which is the opposite of what a caller comparing them needs.
CREATE INDEX proj_execution_plan_summary_name_idx
    ON proj_execution_plan_summary (name);

-- The keyset-pagination sort key, with the id in it for the same
-- tie-breaking reason the run summary's carries one.
CREATE INDEX proj_execution_plan_summary_keyset_idx
    ON proj_execution_plan_summary (created_at DESC, plan_id DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_execution_plan_summary TO keeper_app;

-- Starting at zero so enabling this projection replays every plan already
-- defined, which is what fills the table for a deployment older than it.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_execution_plan_summary')
ON CONFLICT DO NOTHING;
