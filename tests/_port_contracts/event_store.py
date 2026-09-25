"""Behaviour every `EventStore` adapter owes its callers, run against each one.

The unit tier swaps the database for a dict. That is the whole reason it
takes a second instead of a minute, and it means 230 tests are evidence
about handlers only for as long as the dict behaves like the database.
Until this file existed, nothing said it did: fifteen behaviours were
pinned against Postgres and none against the in-memory twin, whose
docstring simply claimed the two matched. Three of four deliberate
divergences planted in the twin survived the whole unit tier.

So the behaviours live here once, and both adapters run them. A driver
in the unit tier points them at the double, a driver in the integration
tier points them at Postgres, and both parametrize over the same
`CHECKS` tuple, so a behaviour added for one runs against the other in
the same commit rather than whenever somebody remembers.

Not everything belongs here. An adapter-specific guarantee stays in that
adapter's own file: enlisting in a caller's transaction and waking a
listener are Postgres facts with nothing on the other side to compare.
A check earns its place here only if both adapters can be expected to
pass it, and one that only one side can satisfy is a divergence to write
down rather than a check to weaken.

One deliberate looseness. A reused event id surfaces as
`asyncpg.UniqueViolationError` from one adapter and `ValueError` from
the other. The shared check asserts what callers actually depend on,
which is that whatever comes back is not a `ConcurrencyError`, because
mapping a generator bug onto the retry path turns it into a loop that
reloads, re-appends the same id and fails identically forever.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from keeper.infrastructure.ports.event_store import (
    ConcurrencyError,
    EventStore,
    NewEvent,
    StreamAppend,
)

Check = Callable[[EventStore], Awaitable[None]]
"""One behaviour, applied to whichever adapter the driver supplies."""


def an_event(event_type: str = "ThingRegistered", *, event_id: UUID | None = None) -> NewEvent:
    """A filled-in event, with a fresh id unless the caller pins one."""
    return NewEvent(
        event_id=event_id or uuid4(),
        event_type=event_type,
        schema_version=1,
        payload={"note": event_type},
        occurred_at=datetime.now(UTC),
        correlation_id=uuid4(),
        metadata={"command": "DoThing"},
        principal_id=uuid4(),
    )


async def _refusal(awaitable: Awaitable[object]) -> Exception:
    """Await something expected to fail, and hand back what it raised.

    Used where the two adapters raise different classes for the same
    mistake, so the check can assert the property both must have rather
    than a type only one of them produces.
    """
    try:
        await awaitable
    except Exception as raised:
        return raised
    msg = "expected a refusal, the call succeeded"
    raise AssertionError(msg)


async def check_appended_events_load_back_in_version_order(store: EventStore) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [an_event("ThingRegistered"), an_event("ThingRenamed")])

    loaded, version = await store.load("thing", stream)
    assert [e.event_type for e in loaded] == ["ThingRegistered", "ThingRenamed"]
    assert [e.version for e in loaded] == [1, 2]
    assert version == 2


async def check_the_first_event_is_version_one_and_append_reports_the_new_version(
    store: EventStore,
) -> None:
    stream = uuid4()
    assert await store.append("thing", stream, 0, [an_event()]) == 1
    assert await store.append("thing", stream, 1, [an_event(), an_event()]) == 3


async def check_loading_a_stream_that_was_never_written_returns_nothing(
    store: EventStore,
) -> None:
    assert await store.load("thing", uuid4()) == ([], 0)


async def check_load_returns_only_the_stream_asked_for(store: EventStore) -> None:
    mine, theirs = uuid4(), uuid4()
    await store.append("thing", mine, 0, [an_event("Mine")])
    await store.append("thing", theirs, 0, [an_event("Theirs")])

    events, _ = await store.load("thing", mine)
    assert [e.event_type for e in events] == ["Mine"]


async def check_two_streams_may_share_an_id_under_different_stream_types(
    store: EventStore,
) -> None:
    """The key is (stream_type, stream_id, version), so one id under two
    types is two streams, each numbered from one.
    """
    shared = uuid4()
    await store.append("thing", shared, 0, [an_event("A")])
    await store.append("other", shared, 0, [an_event("B")])

    thing_events, _ = await store.load("thing", shared)
    other_events, _ = await store.load("other", shared)
    assert [e.event_type for e in thing_events] == ["A"]
    assert [e.event_type for e in other_events] == ["B"]


async def check_a_stale_writer_is_refused_and_told_the_actual_version(
    store: EventStore,
) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [an_event(), an_event()])

    refusal = await _refusal(store.append("thing", stream, 0, [an_event()]))
    assert isinstance(refusal, ConcurrencyError)
    assert refusal.expected == 0
    assert refusal.actual == 2


async def check_a_refused_append_writes_none_of_its_events(store: EventStore) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [an_event("First")])

    await _refusal(store.append("thing", stream, 0, [an_event("Doomed"), an_event("AlsoDoomed")]))
    events, _ = await store.load("thing", stream)
    assert [e.event_type for e in events] == ["First"]


async def check_a_duplicate_event_id_is_not_reported_as_a_concurrency_error(
    store: EventStore,
) -> None:
    """A reused id is a generator bug, and the caller's response to a
    concurrency refusal is to reload and retry, which would never end.
    """
    reused = uuid4()
    await store.append("thing", uuid4(), 0, [an_event(event_id=reused)])

    refusal = await _refusal(store.append("thing", uuid4(), 0, [an_event(event_id=reused)]))
    assert not isinstance(refusal, ConcurrencyError), (
        f"a reused event id came back as {type(refusal).__name__}, which sends "
        "the caller into a retry loop that re-appends the same id forever"
    )


async def check_two_identical_event_ids_in_one_batch_are_refused(store: EventStore) -> None:
    """Same rule, inside a single append rather than across two."""
    reused = uuid4()
    stream = uuid4()

    refusal = await _refusal(
        store.append("thing", stream, 0, [an_event(event_id=reused), an_event(event_id=reused)])
    )
    assert not isinstance(refusal, ConcurrencyError)
    assert await store.load("thing", stream) == ([], 0)


async def check_appending_no_events_reports_the_version_back_and_writes_nothing(
    store: EventStore,
) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [an_event()])

    assert await store.append("thing", stream, 1, []) == 1
    events, _ = await store.load("thing", stream)
    assert len(events) == 1


async def check_a_multi_stream_append_commits_every_stream_or_none_of_them(
    store: EventStore,
) -> None:
    """Why append_streams exists. There is no write that un-appends an
    event, so a saga must not leave one aggregate written and the other not.
    """
    good, stale = uuid4(), uuid4()
    await store.append("thing", stale, 0, [an_event("Existing")])

    refusal = await _refusal(
        store.append_streams(
            [
                StreamAppend("thing", good, 0, [an_event("ShouldNotLand")]),
                StreamAppend("thing", stale, 0, [an_event("Conflicts")]),
            ]
        )
    )
    assert isinstance(refusal, ConcurrencyError)
    assert await store.load("thing", good) == ([], 0), "the other stream rolled back too"


async def check_a_multi_stream_append_that_succeeds_reports_each_new_version(
    store: EventStore,
) -> None:
    one, two = uuid4(), uuid4()
    versions = await store.append_streams(
        [
            StreamAppend("thing", one, 0, [an_event()]),
            StreamAppend("thing", two, 0, [an_event(), an_event()]),
        ]
    )
    assert versions == {one: 1, two: 2}


async def check_a_stream_with_no_events_still_reports_its_version_in_the_result(
    store: EventStore,
) -> None:
    written, empty = uuid4(), uuid4()
    versions = await store.append_streams(
        [
            StreamAppend("thing", written, 0, [an_event()]),
            StreamAppend("thing", empty, 7, []),
        ]
    )
    assert versions == {written: 1, empty: 7}


async def check_a_stored_event_carries_back_the_envelope_it_was_given(
    store: EventStore,
) -> None:
    """Every field the writer supplied survives the trip.

    Equality one field at a time rather than on the whole object, because
    the store adds fields of its own and a reader has to know which of
    them came back unchanged.
    """
    stream = uuid4()
    written = an_event("ThingHappened")
    await store.append("thing", stream, 0, [written])

    (read,), _ = await store.load("thing", stream)
    assert read.event_id == written.event_id
    assert read.event_type == written.event_type
    assert read.schema_version == written.schema_version
    assert read.payload == written.payload
    assert read.occurred_at == written.occurred_at
    assert read.correlation_id == written.correlation_id
    assert read.causation_id == written.causation_id
    assert read.metadata == written.metadata
    assert read.principal_id == written.principal_id
    assert read.stream_type == "thing"
    assert read.stream_id == stream


async def check_every_stored_event_carries_a_commit_watermark_in_order(
    store: EventStore,
) -> None:
    """A projection resumes from (transaction_id, position), so both have
    to be real values and positions have to increase with write order.
    """
    stream = uuid4()
    await store.append("thing", stream, 0, [an_event(), an_event()])

    loaded, _ = await store.load("thing", stream)
    assert all(e.transaction_id > 0 for e in loaded)
    assert loaded[0].position < loaded[1].position


CHECKS: tuple[Check, ...] = (
    check_appended_events_load_back_in_version_order,
    check_the_first_event_is_version_one_and_append_reports_the_new_version,
    check_loading_a_stream_that_was_never_written_returns_nothing,
    check_load_returns_only_the_stream_asked_for,
    check_two_streams_may_share_an_id_under_different_stream_types,
    check_a_stale_writer_is_refused_and_told_the_actual_version,
    check_a_refused_append_writes_none_of_its_events,
    check_a_duplicate_event_id_is_not_reported_as_a_concurrency_error,
    check_two_identical_event_ids_in_one_batch_are_refused,
    check_appending_no_events_reports_the_version_back_and_writes_nothing,
    check_a_multi_stream_append_commits_every_stream_or_none_of_them,
    check_a_multi_stream_append_that_succeeds_reports_each_new_version,
    check_a_stream_with_no_events_still_reports_its_version_in_the_result,
    check_a_stored_event_carries_back_the_envelope_it_was_given,
    check_every_stored_event_carries_a_commit_watermark_in_order,
)
"""Every check above, in the order a reader should meet them.

Hand-written so that a check defined and never listed is a failure rather
than a quiet omission. The drivers guard that.
"""


def checks_defined_but_not_listed() -> frozenset[str]:
    """Check functions defined in this module that `CHECKS` leaves out.

    The tuple is the contract; a function absent from it runs nowhere.
    Deriving the other side from the module's own namespace means adding
    a check and forgetting to list it fails, rather than passing quietly
    with one behaviour fewer than the file appears to promise.
    """
    listed = {check.__name__ for check in CHECKS}
    defined = {
        name for name, value in globals().items() if name.startswith("check_") and callable(value)
    }
    return frozenset(defined - listed)
