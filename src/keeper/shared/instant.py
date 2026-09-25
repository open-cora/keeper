"""When a caller says something happened, as they report it.

Some acts this system records happened somewhere else: an engine ran a
routine, a store wrote a body of data. For those, the moment it happened
and the moment this system was told are two different facts. The envelope
has held both since the beginning: `occurred_at` is domain time and
`recorded_at` is write time. What was missing was any way for a caller to
set the first, so every event said the act happened when the report
arrived.

For a live adapter that gap is milliseconds. For a reporter that was down
for an hour it is an hour, and for a backfill out of an engine's own
archive it is years.

The file is named for what it guarantees rather than for the field it
guards. An instant is a point on the timeline, one that everybody agrees
on whatever offset they write it in, and turning what arrives into one is
the whole of the work here.

It lives in `keeper.shared` because it is pure, imports nothing from
`aroc`, and has three consumers across three bounded contexts. It began
beside the Run aggregate, where the first consumer was, and stayed there
through the second because the rule of three in
docs/reference/layout.md was not met. Commands that describe an act
performed elsewhere are what reach for it, so the set of consumers grows
with contexts of that kind rather than with contexts in general.

## What is checked, and what is not

A timestamp must carry an offset, and it is converted to UTC. Beyond that
it is taken at face value.

The offset is not a formality. `datetime.fromisoformat` returns a naive
value without complaint, and writing one into a `timestamptz` column makes
Postgres apply whatever the session timezone happens to be, so the row
ends up stating a time nobody sent. Refusing it is the only way to know
what was meant.

Converting to UTC does a second job that is easy to miss. The idempotency
wrapper hashes a whole command, so this field joins that hash, and two
spellings of one instant would otherwise be two different hashes: a retry
sending `Z` where the first attempt sent `+00:00` would come back as a
conflict rather than the answer it already had. Normalising first makes
those the same command, which is what they are.

## Why a claimed time is never compared against the clock

Three reasons, and they compound.

A decision function cannot read a clock, by rule and by test, so the
comparison would have to happen in a handler, which is the one layer this
tree keeps domain refusals out of.

The clock is a poor referee anyway. `MonotonicClock` exists because
`Clock.now()` can jump backward under an NTP correction, so "later than
now" is not a stable question to ask of it.

And the answer is recoverable without asking. `recorded_at` is written by
the database, never by this application, so a caller cannot touch it. A
claim that a run finished in the year 9999 sits in the record next to a
write time of today, and any reader can see it for what it is.

That is the posture every context reaching for this takes. An engine's
reported exit status is not second-guessed either. What is promised is
that the record says plainly what was claimed, and separately says when
it was written down.
"""

from datetime import UTC, datetime


class InvalidOccurredAtError(ValueError):
    """A reported timestamp carried no timezone.

    The one thing refused about a claimed time. A naive datetime is not a
    moment, it is a reading off somebody's wall, and there is no way from
    here to know whose wall.

    A shared error class, like `InvalidIdentifierError` beside it, so it
    is mapped to a status by the context that first needed it rather
    than by every context that raises it. Execution does that mapping.
    """

    def __init__(self, value: datetime) -> None:
        super().__init__(
            f"occurred_at {value.isoformat()} has no timezone; "
            "send an offset, such as a trailing Z for UTC"
        )
        self.value = value


def normalize_occurred_at(value: datetime) -> datetime:
    """Refuse a naive timestamp, and return the UTC form of an aware one.

    Returns the same instant, not the same wall-clock reading: a value
    arriving as 14:32+02:00 comes back as 12:32+00:00, which is when it
    happened.

    Called from a command's `__post_init__` rather than from a handler or
    a decision function, so the refusal happens where the value is built
    and both surfaces get it from one place.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidOccurredAtError(value)
    return value.astimezone(UTC)


__all__ = ["InvalidOccurredAtError", "normalize_occurred_at"]
