-- A dispatch announces itself once it is readable, not once it is written.
--
-- The work intake holds an HTTP request open and answers it the instant a
-- dispatch appears for that beamline. Something has to wake it, and the
-- obvious candidate does not work.
--
-- ## Why the existing `events` channel is the wrong signal here
--
-- The baseline migration notifies on every insert into `events`, and the
-- projection worker listens to it. A held intake request listening to the same
-- channel wakes at the same instant the worker does, queries
-- `proj_execution_execution_summary`, and finds nothing: the worker is still
-- inside the transaction that will write the row. The intake then waits again,
-- and no second notify on that channel is coming, because applying a
-- projection inserts no event. So it would sleep to its timeout on nearly
-- every dispatch, and the instant pickup this whole arrangement exists for
-- would quietly never happen.
--
-- This trigger fires where the answer becomes available: after the row the
-- intake query reads has been written. Same shape as the one on `events`, one
-- layer further out.
--
-- ## Still best-effort, and the reader must still poll
--
-- A listener that is not connected at INSERT time never learns of the row, and
-- a notify arriving between a reader's query and its wait is lost. That is
-- true of the `events` channel too and is why the projection worker treats
-- NOTIFY as a latency optimization and the advance query as the source of
-- truth. The intake does the same: it queries, waits, and queries again, with
-- a ceiling on each wait, so a missed notify costs latency until the next look
-- rather than a dispatch nobody picks up. The work is durable at `Dispatched`
-- either way.
--
-- The payload carries the beamline and the status so a future reader can
-- filter without a query. Nothing does that today: one connection per beamline
-- waking on another beamline's dispatch costs one query that returns nothing,
-- and reading the payload would be a second place the filter is written.

CREATE OR REPLACE FUNCTION execution_summary_notify() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'execution_summary',
        json_build_object(
            'execution_id', NEW.execution_id,
            'beamline',     NEW.beamline,
            'status',       NEW.status
        )::text
    );
    RETURN NEW;
END;
$$;

-- AFTER INSERT only. A claim, a step and an ending all UPDATE this row, and
-- none of them puts work into a state the intake is waiting for: they move an
-- execution off `Dispatched` rather than onto it. Notifying on those would
-- wake every held request at every beamline for every step of every execution
-- in flight, which is the one thing a long-poll must not do.
CREATE TRIGGER execution_summary_notify_trigger
    AFTER INSERT ON proj_execution_execution_summary
    FOR EACH ROW
    EXECUTE FUNCTION execution_summary_notify();
