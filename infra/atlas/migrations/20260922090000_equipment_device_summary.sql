-- Equipment's device summary: one row per piece of hardware on the register.
--
-- Maintained by a background worker tailing the event log. Derived data in
-- the strict sense: every column can be recomputed from the `events` table,
-- so dropping the table and resetting the bookmark below to zero rebuilds it
-- exactly. The log is the record; this is a convenience over it.
--
-- It exists because neither question this bounded context is asked can be
-- answered by folding. An adapter holding a control system's address has no
-- device id, and "what is faulted" names no device, and a fold has to know
-- which stream to fold.

-- ---------------------------------------------------------------------------
-- proj_equipment_device_summary
-- ---------------------------------------------------------------------------
-- The table name, the bookmark name below, and the projection's registered
-- name are one string. The worker finds the bookmark by that name and the
-- adapter finds the table by spelling it, so a disagreement is a projection
-- that advances a cursor over rows it never wrote.
--
-- Every column of the aggregate is here, which is the one place this table
-- differs from its three siblings. Each of those drops a field for being
-- unbounded; a device has none. The label is bounded and everything else is
-- an id, a word or a time, so a caller reading a page needs no second call.
--
-- `status` is derived, written by the projection from the event type exactly
-- as the fold derives it. It is text rather than an enum type for the reason
-- the run summary's is: a new disposition would otherwise be a type change on
-- a live table rather than a new string the writer starts emitting.
--
-- No per-transition column. `status` already names which transition was last,
-- and a `faulted_at` beside an `updated_at` would say the same thing twice
-- and let the two disagree.
--
-- Two timestamps from two authorities, which is R8 reaching the read side.
-- `registered_at` can only ever be this system's own clock reading, because
-- enrolling a device is an act performed here. `updated_at` may be a caller's
-- claim, because a fault and a recovery both happened at a beamline at a
-- moment nothing here was present for. A device that has never moved carries
-- the same value in both.

CREATE TABLE proj_equipment_device_summary (
    device_id           uuid        PRIMARY KEY,
    external_ref_scheme text        NOT NULL,
    external_ref_value  text        NOT NULL,
    name                text        NOT NULL,
    status              text        NOT NULL,
    registered_at       timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL
);

-- The lookup an adapter cannot work without: an address to the id it names.
--
-- Not unique, and that is deliberate rather than an omission. Nothing on the
-- write side stops two devices carrying one address, because an event sourced
-- aggregate has no consistency boundary spanning its siblings, so a unique
-- index here would fail the projection rather than the registration and wedge
-- the worker over a row it can never write. The read side returns both and
-- lets the caller see the duplicate.
CREATE INDEX proj_equipment_device_summary_external_ref_idx
    ON proj_equipment_device_summary (external_ref_scheme, external_ref_value);

-- The operator's question: what is broken right now.
--
-- Partial, because the query only ever asks for the faulted side, and on a
-- healthy deployment that is a small fraction of the table. The complementary
-- queries are served by the keyset index below, which is expected to match
-- most rows and so earns less than a scan would cost to maintain separately.
CREATE INDEX proj_equipment_device_summary_faulted_idx
    ON proj_equipment_device_summary (registered_at DESC, device_id DESC)
    WHERE status = 'Faulted';

-- The keyset-pagination sort key. `device_id` is in it rather than only in
-- the output because two devices registered at the same instant have no
-- defined order between them otherwise, and a page boundary landing inside
-- such a tie repeats a row or skips one.
--
-- That tie is likely here rather than hypothetical: a facility's register is
-- normally populated in one pass, by a script enrolling every motor on a
-- beamline, and `registered_at` is this system's own clock.
CREATE INDEX proj_equipment_device_summary_keyset_idx
    ON proj_equipment_device_summary (registered_at DESC, device_id DESC);

-- No index on the label, because nothing filters on it. It is there for a
-- person reading a row, not for finding one.

-- Full DML, unlike `events`. A projection table is rewritten by the worker as
-- events arrive and is rebuilt from scratch when its logic changes, so the
-- append-only guarantee that protects the log would make this unmaintainable.
GRANT SELECT, INSERT, UPDATE, DELETE ON proj_equipment_device_summary TO keeper_app;

-- The worker reads its cursor by name and raises when the row is missing, so
-- seeding it belongs with the table it tracks. Starting at zero rather than at
-- the current head means enabling this projection replays everything already
-- recorded, which is what fills the table for a deployment that has been
-- running since before it existed.
INSERT INTO projection_bookmarks (name)
VALUES ('proj_equipment_device_summary')
ON CONFLICT DO NOTHING;
