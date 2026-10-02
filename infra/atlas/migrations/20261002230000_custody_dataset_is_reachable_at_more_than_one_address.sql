-- One body of data is commonly at two addresses at once, and the row could
-- only hold one.
--
-- A copy to central storage leaves the beamline copy in place until something
-- purges it, and that window is days to weeks. It is also exactly the window
-- in which anything would want to read the data. With a single pair of
-- columns the projection had to be swapped at the moment of the copy, and
-- that swap is wrong for the whole of the window: it says the data left a
-- disk it is still on, and a caller that could have read the near copy is
-- sent to the far one or to neither.
--
-- ## Why one column rather than a second table
--
-- A table of addresses would be the ordinary shape and it costs a join on
-- the one query this projection exists to serve, plus a second cursor
-- problem: the listing pages by `(created_at, dataset_id)` and a joined row
-- set no longer has one row per page entry.
--
-- The thing a separate table would buy is enforcing uniqueness per address
-- with an index. That is not wanted here for the reason the dataset table
-- already declined a unique index on the old pair: refusing a duplicate by
-- dropping a row leaves a record that exists in the log missing from every
-- listing. Uniqueness within one dataset is enforced on the write path,
-- where it can be refused out loud.
--
-- ## Why jsonb and not two parallel arrays
--
-- Two `text[]` columns can disagree in length, and nothing in the database
-- would say so. A scheme matched to the wrong value is an address that
-- resolves somewhere real and wrong, which is the worst kind. One array of
-- two-key objects cannot come apart, and jsonb compares objects by content
-- rather than by key order, which is what lets the projection remove an
-- address by equality instead of by position.
--
-- ## Why this backfills rather than rebuilding
--
-- The table is derived and could be truncated and replayed, which is what a
-- new projection does. Here the old columns already hold exactly what the
-- log would produce for the one event type that has ever been written, so
-- carrying them across is both cheaper and leaves no window in which the
-- listing answers "no datasets" while datasets exist. The bookmark is left
-- where it is: the two new event types have never been emitted, so there is
-- nothing behind it to re-read.

ALTER TABLE proj_custody_dataset_summary
    ADD COLUMN external_refs jsonb NOT NULL DEFAULT '[]'::jsonb;

UPDATE proj_custody_dataset_summary
SET external_refs = jsonb_build_array(
        jsonb_build_object('scheme', external_ref_scheme, 'value', external_ref_value)
    );

ALTER TABLE proj_custody_dataset_summary
    ALTER COLUMN external_refs DROP DEFAULT,
    DROP COLUMN external_ref_scheme,
    DROP COLUMN external_ref_value;
