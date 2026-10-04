-- A device says which beamline it is at, and which cluster it belongs to.
--
-- One installation serves four beamlines and the register could not be asked
-- about any of them. Listing the devices at 19-BM meant reading every device
-- everywhere and matching on the shape of an address, which is a convention
-- nothing in this system enforces. `beamline` makes it a query.
--
-- `group` is the functional cluster a device belongs to at that beamline: a
-- sample stack, a set of slits, the filters. It is nullable because most
-- records honestly belong to none. A motor whose only description is the
-- channel it occupies in a crate is not part of anything anybody has named,
-- and a value there would be invented rather than recorded.
--
-- The pair is meant together. A group name means different hardware at each
-- beamline, so a group without a beamline beside it does not pick out a set.
--
-- ## What this is not
--
-- Not a catalog. There is no group table and no foreign key, because a group
-- is a value rows share rather than a thing that owns them: it exists while
-- some device says that word and stops existing when the last one stops. No
-- nesting, no ordering, and nothing that can be said about a group rather
-- than about a device. `beamlines/README.md` refuses the catalog and this
-- does not smuggle one in under a column name.
--
-- ## Dropped and rebuilt rather than altered
--
-- `beamline` is NOT NULL and no existing row could supply a value, so an
-- ALTER would need a default that means nothing. This table is derived, the
-- events behind it are all still in the log, and the bookmark below starts at
-- zero, so the worker recomputes every row from the genesis events on its
-- next pass. That is the pattern every projection change in this tree uses.
--
-- The event payloads are the different matter. `DeviceRegistered` now carries
-- both keys and a row written before it does not, so a device registered
-- earlier fails to load rather than folding without them. Acceptable for the
-- reason the procedure beamline migration gives: nothing is deployed and no
-- device in any database anybody keeps was ever published.

DROP TABLE IF EXISTS proj_equipment_device_summary;  -- atlas:safety:allow=projection table, rebuilt from the event log

-- `group` is a reserved word in SQL, so it is quoted here and everywhere it
-- is read. The alternative was a column name that does not match the field,
-- and a rename at the storage boundary is the kind of thing a reader has to
-- hold in their head for no benefit.
CREATE TABLE proj_equipment_device_summary (
    device_id           uuid        PRIMARY KEY,
    external_ref_scheme text        NOT NULL,
    external_ref_value  text        NOT NULL,
    name                text        NOT NULL,
    beamline            text        NOT NULL,
    "group"             text,
    status              text        NOT NULL,
    registered_at       timestamptz NOT NULL,
    updated_at          timestamptz NOT NULL
);

CREATE INDEX proj_equipment_device_summary_external_ref_idx
    ON proj_equipment_device_summary (external_ref_scheme, external_ref_value);

CREATE INDEX proj_equipment_device_summary_faulted_idx
    ON proj_equipment_device_summary (registered_at DESC, device_id DESC)
    WHERE status = 'Faulted';

CREATE INDEX proj_equipment_device_summary_keyset_idx
    ON proj_equipment_device_summary (registered_at DESC, device_id DESC);

-- The beamline filter, with the group beside it because a caller narrowing to
-- a beamline is usually about to read the groups in it, and a covering index
-- answers that without touching the heap.
--
-- No index on `"group"` alone. Nothing filters on it: the column is returned
-- so a caller can group a beamline's listing with what it already has, and
-- `summary.py` declines the server-side filter for want of a caller. An index
-- for a query nobody makes is the same waste as the parameter.
CREATE INDEX proj_equipment_device_summary_beamline_idx
    ON proj_equipment_device_summary (beamline, "group");

GRANT SELECT, INSERT, UPDATE, DELETE ON proj_equipment_device_summary TO keeper_app;

-- Recreated, so the bookmark goes too and starts at zero. The worker raises
-- on a registered projection with no bookmark, and replaying from the start
-- is what refills the table.
DELETE FROM projection_bookmarks WHERE name = 'proj_equipment_device_summary';

INSERT INTO projection_bookmarks (name)
VALUES ('proj_equipment_device_summary')
ON CONFLICT DO NOTHING;
