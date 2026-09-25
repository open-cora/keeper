"""Read device summaries out of the projection table.

The deployment half of the `DeviceSummaryLookup` port. One SELECT
against `proj_equipment_device_summary`, which a background worker keeps
in step with the device streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(registered_at, device_id)`, and the id
is in the sort key rather than only in the output. Two devices enrolled
at the same instant, which a script populating a beamline's register
produces routinely, would otherwise have no defined order between them,
and a page boundary landing in the middle of such a tie either repeats a
row or skips one. The id breaks every tie the same way on every page.

That pair is also what the cursor carries, which is why the comparison
below is a row comparison rather than two ANDed inequalities. Postgres
can use the index for the row form.

## Why the page orders on registration and not on the update

`updated_at` is the more interesting column and it is the wrong sort
key. It moves, so a device faulting while a caller pages would jump to
the front and be seen twice, or jump past the cursor and be missed. A
keyset cursor needs a key that does not move, and the only one here is
when the device was enrolled.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned.
Its presence is the whole answer to "is there a next page", and asking
that way costs one row rather than a second COUNT query over the table.
The cursor handed back is the sort key of the LAST row actually
returned, so the next page resumes exactly where this one stopped.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.equipment.aggregates.device.state import DeviceStatus
from keeper.equipment.aggregates.device.summary import DeviceSummary, DeviceSummaryPage
from keeper.equipment.projections.device_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor
from keeper.shared.identifier import Identifier

_SELECT_SQL = f"""
SELECT device_id, external_ref_scheme, external_ref_value, name,
       status, registered_at, updated_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR external_ref_scheme = $1)
  AND ($2::text IS NULL OR external_ref_value = $2)
  AND ($3::text IS NULL OR status = $3)
  AND ($4::timestamptz IS NULL OR (registered_at, device_id) < ($4, $5))
ORDER BY registered_at DESC, device_id DESC
LIMIT $6
"""


class PostgresDeviceSummaryLookup:
    """Postgres-backed implementation of the `DeviceSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_devices(
        self,
        *,
        external_ref: Identifier | None,
        status: DeviceStatus | None,
        limit: int,
        cursor: str | None,
    ) -> DeviceSummaryPage:
        """Return one page of devices, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            external_ref.scheme if external_ref is not None else None,
            external_ref.value if external_ref is not None else None,
            status.value if status is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].registered_at, item_id=items[-1].device_id)
            if has_more and items
            else None
        )
        return DeviceSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> DeviceSummary:
    return DeviceSummary(
        device_id=row["device_id"],
        external_ref=Identifier(
            scheme=row["external_ref_scheme"],
            value=row["external_ref_value"],
        ),
        name=row["name"],
        status=DeviceStatus(row["status"]),
        registered_at=row["registered_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresDeviceSummaryLookup"]
