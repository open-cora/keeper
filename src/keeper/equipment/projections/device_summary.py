"""Keep `proj_equipment_device_summary` in step with the device streams.

Four event types over two statements, which makes it the widest of the
four projections in this tree and also the flattest: one INSERT for the
genesis and one UPDATE that all three transitions share, differing only
in the status word each maps to.

## The name is three things at once

`proj_equipment_device_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker
finds the bookmark by the name and the SQL below finds the table by
spelling it, and `test_projections_have_a_table_and_a_bookmark.py` is
what makes the agreement a rule rather than a habit.

## The status is derived here too

The event type decides the status, exactly as it does in the fold. That
is the same derivation written a second time, in a second language,
which is a duplication worth naming: `_STATUS_BY_EVENT` below and the
evolver's match arms have to agree or a row will disagree with the
stream behind it. They are pinned together by the port contract suite,
which runs one set of assertions against both this table and a fold over
the same events.

The alternative would be to put the status on the payload so both sides
read one value. That is worse, and the aggregate says why: a status a
writer can set is a status a writer can set wrong, and the whole reason
it is derived is that it then cannot contradict the history.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch,
and a replayed batch has to leave the table where the first pass left it.

The genesis takes `ON CONFLICT (device_id) DO NOTHING`. The transition
is idempotent for a different reason and it is worth being explicit: it
writes the same two values every time, derived entirely from the event
rather than from what the row currently holds, so applying it twice is
applying it once.

## Why the update is not conditional

The transition writes status and time over whatever is there, without
checking what the row currently says. The decider already refuses every
transition the state does not allow, so a stream carrying an impossible
sequence is a stream that could not have been written, and an arm
defending against it would be defending against a state the write side
makes impossible.

What the arm does handle is the row not being there at all. That means
the genesis is missing, which the ordering guarantees cannot happen:
events arrive in `(transaction_id, position)` order and a device's own
events share a stream. It is logged rather than raised, because the
alternative is wedging the whole projection over one device, and a
warning naming it is what an operator needs to rebuild.
"""

from typing import Any

from keeper.equipment.aggregates.device.state import DeviceStatus
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_equipment_device_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "DeviceRegistered"

_STATUS_BY_EVENT: dict[str, DeviceStatus] = {
    "DeviceFaulted": DeviceStatus.FAULTED,
    "DeviceRecovered": DeviceStatus.AVAILABLE,
    "DeviceRetired": DeviceStatus.RETIRED,
}
"""Which status each transition leaves the device in.

The evolver's match arms say the same thing, and the two are pinned
together by the port contract suite rather than by inspection. Adding a
transition event means adding it here as well, and the subscription set
below is built from this map so a new key is subscribed by construction.
"""

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    device_id, external_ref_scheme, external_ref_value, name, status,
    registered_at, updated_at
) VALUES ($1, $2, $3, $4, $5, $6, $6)
ON CONFLICT (device_id) DO NOTHING
"""

_TRANSITION_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2, updated_at = $3
WHERE device_id = $1
"""

_log = get_logger(__name__)


class DeviceSummaryProjection:
    """Folds device events into one row per device."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE}) | frozenset(_STATUS_BY_EVENT)

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where
        it was, so an event this cannot handle is retried forever rather
        than skipped. That is the right failure for a read model: stale
        and loud beats wrong and quiet.
        """
        if event.event_type == _GENESIS_EVENT_TYPE:
            await self._insert(event, conn)
            return
        await self._transition(event, conn)

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row, available.

        `device_id` comes off the envelope rather than the payload: the
        stream id is what both statements here agree on, and reading it
        from the payload would let a malformed row point one statement
        at a different device than the other.

        `registered_at` is the envelope's domain time, which for this
        event is this system's own clock reading, because enrolling a
        device is an act performed here rather than one reported to it.
        It is written into `updated_at` as well, so a device that has
        never moved has a real value in both rather than a null a reader
        has to interpret.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            payload["external_ref_scheme"],
            payload["external_ref_value"],
            payload["device_name"],
            DeviceStatus.AVAILABLE.value,
            event.occurred_at,
        )

    async def _transition(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Move an existing row to its new status, or say so when there is none.

        `updated_at` is the envelope's domain time, which for a fault or
        a recovery may be a caller's claim rather than a clock reading,
        because both happened at a beamline. For a retirement it is this
        system's clock. Two authorities on one column is R8 reaching the
        read side.
        """
        status = _STATUS_BY_EVENT[event.event_type]
        result = await conn.execute(
            _TRANSITION_SQL,
            event.stream_id,
            status.value,
            event.occurred_at,
        )
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "device_summary.transition_without_row",
                projection=PROJECTION_NAME,
                device_id=str(event.stream_id),
                event_type=event.event_type,
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "DeviceSummaryProjection"]
