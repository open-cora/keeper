-- A question announces itself once it is readable, not once it is written.
--
-- Something that thinks holds an HTTP request open and answers it the instant
-- an inquiry nobody has taken up appears. Something has to wake it, and the
-- obvious candidate does not work.
--
-- This is the second of these. The first, on the execution summary next door,
-- carries the long version of every argument below; what follows says what is
-- the same and what is not.
--
-- ## Why the existing `events` channel is the wrong signal here
--
-- The baseline migration notifies on every insert into `events`, and the
-- projection worker listens to it. A held request listening to the same
-- channel wakes at the same instant the worker does, queries
-- `proj_counsel_inquiry_summary`, and finds nothing: the worker is still
-- inside the transaction that will write the row. It then waits again, and no
-- second notify on that channel is coming, because applying a projection
-- inserts no event. So it would sleep to its ceiling on nearly every question,
-- and the instant pickup this exists for would quietly never happen.
--
-- This trigger fires where the answer becomes available: after the row the
-- waiting query reads has been written.
--
-- ## Why AFTER INSERT, which here is the whole of the state it waits for
--
-- An inquiry is Open the moment it lands, because Open is `claimed_at` and
-- `answered_at` both being null and the genesis insert writes them that way.
-- So the insert is exactly the transition a waiting thinker is waiting for,
-- and there is no second one it would want.
--
-- A claim and an answer are UPDATEs, and both move an inquiry OFF Open.
-- Notifying on those would wake every held request for work that has just
-- stopped being available, which is the one thing a long poll must not do.
--
-- A replayed batch does not re-announce, and that falls out of the projection
-- rather than being arranged here: the genesis insert is ON CONFLICT DO
-- NOTHING, and a row trigger does not fire for a row that was not inserted.
--
-- ## Still best-effort, and the reader must still poll
--
-- A listener that is not connected at INSERT time never learns of the row, and
-- a notify arriving between a reader's query and its wait is lost. That is
-- true of the `events` channel too, and is why the projection worker treats
-- NOTIFY as a latency optimization and the advance query as the source of
-- truth. A held request does the same: it queries, waits with a ceiling, and
-- queries again, so a missed notify costs latency until the next look rather
-- than a question nobody picks up. The work is durable at Open either way.
--
-- The payload carries the ids and nothing reads it. Unlike the execution
-- summary's, it names nothing a reader could filter on, because there is
-- nothing to filter: an inquiry carries the execution it asks about and no
-- beamline of its own, so a thinker going looking asks for any open question
-- rather than for its own share of them. What the payload is for is somebody
-- watching the channel by hand to find out whether it fires.

CREATE OR REPLACE FUNCTION counsel_inquiry_summary_notify() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify(
        'counsel_inquiry_summary',
        json_build_object(
            'inquiry_id',   NEW.inquiry_id,
            'execution_id', NEW.execution_id
        )::text
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER counsel_inquiry_summary_notify_trigger
    AFTER INSERT ON proj_counsel_inquiry_summary
    FOR EACH ROW
    EXECUTE FUNCTION counsel_inquiry_summary_notify();
