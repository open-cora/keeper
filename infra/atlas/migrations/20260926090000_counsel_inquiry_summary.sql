-- Counsel's inquiry summary: one row per question somebody put to a thinker.
--
-- Maintained by a background worker tailing the event log. Derived data in
-- the strict sense: every column can be recomputed from the `events` table,
-- so dropping the table and resetting the bookmark below to zero rebuilds it
-- exactly. The log is the record; this is a convenience over it.
--
-- It exists because neither question an operator asks of this aggregate names
-- an inquiry. "What is nobody thinking about" and "what has something been
-- thinking about since yesterday" both have to range over every stream, and a
-- fold has to know which stream to fold.

-- ---------------------------------------------------------------------------
-- proj_counsel_inquiry_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- The objective is here, where the proposal table's parameters are not. The
-- reason is the bound: parameters are unbounded and would make a page of
-- fifty rows mostly parameters, and an objective is capped, partly so that it
-- can ride here. A list of questions with the questions taken out is a list
-- of identifiers, and nobody scanning for the one they care about can use it.
--
-- There is no status column, which is the call the proposal table next door
-- makes for two states and this one makes for three. `claimed_at` and
-- `answered_at` carry the whole of it:
--
--     Open      both null
--     Claimed   claimed_at set, answered_at null
--     Answered  answered_at set, whatever claimed_at says
--
-- A status column beside them would be the same fact written twice, and two
-- spellings of one fact are two things a projection can write inconsistently.
-- The read side derives the word from the same two columns.
--
-- Answering without claiming is ordinary rather than a gap. A thinker handed
-- its question never claims, so a row can reach `answered_at` with
-- `claimed_at` still null, and the derivation above says Answered for it.
--
-- `execution_step_count` is not nullable and the three answer columns are.
-- The count is captured when the question is put, from the execution itself;
-- the other three arrive with the answer, and all three arrive together from
-- one event, so a row holding one of them without the others is not a row
-- this projection can produce.
--
-- Three timestamps from two authorities, which is R8 reaching the read side.
-- `created_at` can only ever be this system's own clock reading, because
-- asking is an act performed here. `claimed_at` and `answered_at` may both be
-- a caller's claim, because a thinker picks work up and concludes on its own
-- clock.

CREATE TABLE proj_counsel_inquiry_summary (
    inquiry_id           uuid        PRIMARY KEY,
    actor_id             uuid        NOT NULL,
    execution_id         uuid        NOT NULL,
    objective            text        NOT NULL,
    execution_step_count integer     NOT NULL,
    conclusion           text,
    observed_step_count  integer,
    execution_ended      boolean,
    proposal_id          uuid,
    created_at           timestamptz NOT NULL,
    claimed_at           timestamptz,
    answered_at          timestamptz
);

-- The staleness lookup: questions something took up and has not come back
-- from. Partial, because that is the only side this index is asked for, and
-- a row leaves it the moment an answer lands.
--
-- Nothing expires a claim, so this index is the whole of the mechanism. An
-- orphaned thinker is a row that stays here, and `claimed_at` is how long it
-- has been one. A rule that released the work instead would be releasing
-- work this system cannot prove was abandoned.
CREATE INDEX proj_counsel_inquiry_summary_claimed_idx
    ON proj_counsel_inquiry_summary (created_at DESC, inquiry_id DESC)
    WHERE claimed_at IS NOT NULL AND answered_at IS NULL;

-- The other lookup a thinker makes: questions nobody has taken up. Partial
-- for the same reason, and it is the one a thinker going looking for work
-- reads.
CREATE INDEX proj_counsel_inquiry_summary_open_idx
    ON proj_counsel_inquiry_summary (created_at DESC, inquiry_id DESC)
    WHERE claimed_at IS NULL AND answered_at IS NULL;

-- The keyset-pagination sort key. `inquiry_id` is in it rather than only in
-- the output because two inquiries made at the same instant have no defined
-- order between them otherwise, and a page boundary landing inside such a tie
-- repeats a row or skips one.
--
-- The tie is as likely here as it is next door, and for the same reason: the
-- timestamp is this system's own clock rather than a caller's claim, so an
-- agent asking several questions in one turn can land them inside one tick.
CREATE INDEX proj_counsel_inquiry_summary_keyset_idx
    ON proj_counsel_inquiry_summary (created_at DESC, inquiry_id DESC);

-- No index on the asker and none on the execution, because nothing asks yet.
-- An index maintained for nobody is a write cost with no reader.

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_counsel_inquiry_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_counsel_inquiry_summary')
ON CONFLICT DO NOTHING;
