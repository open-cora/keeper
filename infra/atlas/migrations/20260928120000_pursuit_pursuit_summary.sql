-- Pursuit's summary: one row per standing authorization a person has given.
--
-- Maintained by a background worker tailing the event log. Derived data in
-- the strict sense: every column can be recomputed from the `events` table,
-- so dropping the table and resetting the bookmark below to zero rebuilds it
-- exactly. The log is the record; this is a convenience over it.
--
-- It exists because neither question an operator asks of this aggregate names
-- a pursuit. "What may dispatch work at my beamline" and "which loops are
-- waiting for me" both have to range over every stream, and a fold has to
-- know which stream to fold.
--
-- The first of those is the one that makes this different from the sibling
-- read models. A pursuit authorizes a machine to run work at a beamline
-- without asking again, so somebody standing at that beamline needs to be
-- able to enumerate every one that can. A list nobody can filter by beamline
-- would make them page through the whole facility to find out.

-- ---------------------------------------------------------------------------
-- proj_pursuit_pursuit_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- There IS a status column, which is the opposite call to the inquiry table
-- next door, and the reason is that a pursuit's states go backwards. An
-- inquiry is claimed and then answered and never returns, so two nullable
-- timestamps carry the whole of it. A pursuit is held and then resumed and
-- may be held again, so a pair of timestamps would have to record the last of
-- an unbounded sequence rather than whether something happened.
--
-- That makes this the one read model in the tree whose status is written
-- rather than derived, and so the one that can disagree with the fold. What
-- keeps it honest is that both sides answer one port contract suite and
-- neither can see the other.
--
-- `held_for` is set only while the status is Held. It says which of the two
-- answerable conclusions stopped the loop, because a person triaging a page
-- of held pursuits wants to tell "this one is waiting for you" from "this one
-- ran out of ideas": the first needs attention and the second needs data.
--
-- `round_count` is written from the round's own index rather than by
-- incrementing what is there. That is what makes the arm idempotent: delivery
-- is at-least-once, and a counter that read the row first would count a
-- redelivered round twice.
--
-- The budget is not here and neither is what has been spent against it. Five
-- numbers against five limits, one of which depends on the clock at the
-- moment of asking, so a row could not hold that one and a page of fifty
-- would be mostly arithmetic. Reading one pursuit gives all of it.
--
-- Both timestamps are this system's own clock reading. Every event this row
-- is built from is on the makes side of R8, which is what makes this row
-- different from the inquiry's three timestamps from two authorities. The one
-- describing event this aggregate has, a charge, touches no column here.

CREATE TABLE proj_pursuit_pursuit_summary (
    pursuit_id  uuid        PRIMARY KEY,
    actor_id    uuid        NOT NULL,
    goal        text        NOT NULL,
    beamline    text        NOT NULL,
    status      text        NOT NULL,
    held_for    text,
    round_count integer     NOT NULL,
    created_at  timestamptz NOT NULL,
    stopped_at  timestamptz
);

-- The beamline lookup, and the one this table exists for. Not partial: an
-- operator asking what is authorized at their beamline wants the stopped ones
-- too, because "what ran here last night" is the same question a few hours
-- later.
CREATE INDEX proj_pursuit_pursuit_summary_beamline_idx
    ON proj_pursuit_pursuit_summary (beamline, created_at DESC, pursuit_id DESC);

-- The triage lookup: loops that have stopped asking and are waiting for a
-- person. Partial, because that is the only status narrow enough to be worth
-- its own index, and a row leaves it the moment somebody resumes.
CREATE INDEX proj_pursuit_pursuit_summary_held_idx
    ON proj_pursuit_pursuit_summary (created_at DESC, pursuit_id DESC)
    WHERE status = 'Held';

-- The keyset-pagination sort key. `pursuit_id` is in it rather than only in
-- the output because two pursuits started at the same instant have no defined
-- order between them otherwise, and a page boundary landing inside such a tie
-- repeats a row or skips one.
--
-- The tie is less likely here than next door, because a person starts a
-- pursuit and people do not start two in one tick. It is in the key anyway:
-- the cost is nothing and the alternative is a page that is correct only
-- while nobody scripts it.
CREATE INDEX proj_pursuit_pursuit_summary_keyset_idx
    ON proj_pursuit_pursuit_summary (created_at DESC, pursuit_id DESC);

-- No index on the actor, because nothing asks whose pursuits these are yet.
-- An index maintained for nobody is a write cost with no reader.

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_pursuit_pursuit_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_pursuit_pursuit_summary')
ON CONFLICT DO NOTHING;
