"""HTTP door for reading the event log in commit order.

`GET /events`, oldest first, from a cursor the caller holds. The one read
in this system that crosses every bounded context, because the log does.

## Why this is a chassis route and not a slice

Every other operation is a vertical slice inside the context that owns
the model it touches, published twice, as a route and as an MCP tool. The
log is owned by no context: it is the table all seven write into, and its
cursor and its advance are declared in `keeper.infrastructure`. A slice
for it would have to live in a context that does not own what it reads.

So it sits with `/health`, `/readyz` and `/metrics`, the other routes that
answer for the whole application, and it is not on the generated surface
page, which lists the operations a context publishes.

There is no MCP twin, for the reason `list_executions` gives for keeping
`wait` off its own tool: an agent holding a call open for half a minute is
a different thing wanting a different answer. An agent asking what is
happening has seven contexts' read tools already, and each answers with
current state, which is what an agent wants and what a transition is not.

## What a reader may see

Two commands, and the split is the one the deployed policy already draws.
`GetActor` and `GetPolicy` are the administrator's alone, so the streams
behind them, Actor and Policy, are the administrator's alone here too.
Everything else in the log is already readable through the per-context
reads every principal holds, so granting `ReadEventLog` widens nobody's
reach; it changes the shape of the answer rather than its extent.

`ReadFullEventLog` adds those two streams back. It is what an audit of the
rulebook needs, and the rulebook is the one thing in here that describes
who may do what.

The filter is an allow list rather than a deny list, so an aggregate added
later is invisible until somebody names it.
`tests/architecture/test_the_log_read_mirrors_the_admin_only_reads.py`
fails when a new stream type appears in the tree and not in these sets,
which is what makes the omission a decision rather than an oversight.

## What this route cannot do, and will not pretend to

There is no `beamline` parameter. Three events carry a beamline, and each
of them opens a stream: a dispatch, a pursuit starting and a device being
registered. Nothing that follows one carries it, so a server-side filter
would return the first event of each thread and silently drop the claim,
every step outcome, every engine report and the whole of Counsel.

The beamline describes the stream rather than the event, and turning that
into a filter means a join this route will not make: it would have to know
Execution's payload shape to do it, which is the boundary the rest of the
keeper is organised around. A reader wanting one beamline folds the
stream-opening events as they pass, which is a dictionary and a lookup on
the client side.
"""

from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from pydantic import BaseModel

from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import Deny, EventLogReader, LogCursor, LogPage
from keeper.infrastructure.projection.cursor import decode_log_cursor, encode_log_cursor
from keeper.infrastructure.projection.long_poll import await_a_row
from keeper.infrastructure.projection.wakeup import WakeupSource
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.shared.unauthorized import UnauthorizedError

READ_EVENT_LOG: Final = "ReadEventLog"
"""Reads every stream whose per-context reads are granted to everyone."""

READ_FULL_EVENT_LOG: Final = "ReadFullEventLog"
"""Reads every stream, including the two behind the administrator's reads."""

ADMIN_ONLY_STREAM_TYPES: Final = frozenset({"Actor", "Policy"})
"""The streams behind `GetActor` and `GetPolicy`, which no beamline holds.

Policy is the rulebook, so a reader of it learns which principal may issue
which command where. Actor carries an id and a time and nothing else, and
is here because its read is withheld, not because the rows say much.
"""

ALL_STREAM_TYPES: Final = frozenset(
    {
        "Actor",
        "Dataset",
        "Device",
        "Execution",
        "Inquiry",
        "Operation",
        "Policy",
        "Procedure",
        "Proposal",
        "Pursuit",
    }
)
"""Every stream type any aggregate in this tree opens.

Literals rather than the ten `*_STREAM_TYPE` constants that declare them,
because `tach.toml` does not let this module reach into an aggregate
namespace and should not: the door it would have to cut is one every
chassis route would then hold. The coupling is by string, which is the
shape `tach.toml` already names for a dependency it cannot constrain, and
the check that makes it safe is an architecture test comparing this set
against every declaration in the tracked source, both ways.
"""

GENERAL_STREAM_TYPES: Final = ALL_STREAM_TYPES - ADMIN_ONLY_STREAM_TYPES

DEFAULT_PAGE_SIZE: Final = 100
MAX_PAGE_SIZE: Final = 500

MAX_WAIT_SECONDS: Final = 60.0
"""The longest a caller may ask this route to hold its request open.

A ceiling on the socket rather than on the wait anybody wants, matching
the work intake's. Connections held open indefinitely die in proxies and
NAT tables without telling either end.
"""


class LoggedEventResponse(BaseModel):
    """One event as the log shows it.

    The envelope and the payload, which is the whole row minus the two
    columns that describe where it sits rather than what happened:
    `version` is the stream's own count and `transaction_id` belongs to
    the cursor, which is handed back opaque.

    `correlation_id` is the thread. A pursuit round, the inquiry it
    raises, the proposal that answers it and the execution that follows
    all carry one, which is the join no other read in this system offers.
    """

    position: int
    event_id: UUID
    stream_type: str
    stream_id: UUID
    event_type: str
    schema_version: int
    payload: dict[str, Any]
    metadata: dict[str, Any]
    correlation_id: UUID
    causation_id: UUID | None
    principal_id: UUID | None
    occurred_at: datetime
    recorded_at: datetime


class EventLogResponse(BaseModel):
    """One page of the log, and the cursor that continues it.

    `next_cursor` is null on an empty page, so a caller that waited and
    got nothing keeps the cursor it already had rather than being handed
    one it cannot tell apart from where it started.
    """

    items: list[LoggedEventResponse]
    next_cursor: str | None


router = APIRouter(tags=["log"])


def get_deps(request: Request) -> Kernel:
    """The kernel this request authorizes against.

    Public, unlike the other two below, because a test narrowing the
    grants overrides it. A private name would leave the one seam worth
    overriding reachable only by mutating application state.
    """
    deps: Kernel = request.app.state.deps
    return deps


def _get_reader(request: Request) -> EventLogReader:
    deps: Kernel = request.app.state.deps
    return deps.event_log


def _get_signal(request: Request) -> WakeupSource:
    signal: WakeupSource = request.app.state.log_signal
    return signal


async def _visible_stream_types(
    deps: Kernel,
    *,
    principal_id: UUID,
    surface_id: UUID,
) -> frozenset[str]:
    """Which streams this principal may read, from the two grants.

    Both are asked, and what they permit is unioned rather than ordered.
    A principal holding only the full grant is not thereby refused the
    general streams, which an if-else on the narrower one would do.
    """
    visible: frozenset[str] = frozenset()
    for command_name, grants in (
        (READ_EVENT_LOG, GENERAL_STREAM_TYPES),
        (READ_FULL_EVENT_LOG, ALL_STREAM_TYPES),
    ):
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=command_name,
            surface_id=surface_id,
        )
        if not isinstance(decision, Deny):
            visible = visible | grants
    return visible


@router.get(
    "/events",
    response_model=EventLogResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read the event log.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="Read the event log",
)
async def read_event_log(
    deps: Annotated[Kernel, Depends(get_deps)],
    reader: Annotated[EventLogReader, Depends(_get_reader)],
    signal: Annotated[WakeupSource, Depends(_get_signal)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    after: Annotated[
        str | None,
        Query(
            description="Carry on from the cursor a previous response returned. "
            "Omitted reads from the beginning of the log.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    wait: Annotated[
        float,
        Query(
            ge=0,
            le=MAX_WAIT_SECONDS,
            description="Hold the request open for up to this many seconds rather than "
            "answering an empty page, and return as soon as anything commits. How a "
            "reader tails the log without polling. Zero answers at once.",
        ),
    ] = 0.0,
) -> EventLogResponse:
    _ = cid
    visible = await _visible_stream_types(deps, principal_id=principal_id, surface_id=surface_id)
    if not visible:
        raise UnauthorizedError("principal may not read the event log")

    cursor = LogCursor.BEGINNING
    if after is not None:
        transaction_id, position = decode_log_cursor(after)
        cursor = LogCursor(transaction_id=transaction_id, position=position)

    wanted = sorted(visible)

    async def read() -> LogPage:
        return await reader.read_after(cursor, limit=limit, stream_types=wanted)

    page = await read()
    if not page.items and wait > 0:
        page = await await_a_row(read, signal, wait)

    return EventLogResponse(
        items=[
            LoggedEventResponse(
                position=event.position,
                event_id=event.event_id,
                stream_type=event.stream_type,
                stream_id=event.stream_id,
                event_type=event.event_type,
                schema_version=event.schema_version,
                payload=event.payload,
                metadata=event.metadata,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                principal_id=event.principal_id,
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
            )
            for event in page.items
        ],
        next_cursor=(
            encode_log_cursor(
                transaction_id=page.next_cursor.transaction_id,
                position=page.next_cursor.position,
            )
            if page.next_cursor is not None
            else None
        ),
    )


def register_event_log_route(app: FastAPI) -> None:
    """Mount the log read on the application."""
    app.include_router(router)


__all__ = [
    "ADMIN_ONLY_STREAM_TYPES",
    "ALL_STREAM_TYPES",
    "DEFAULT_PAGE_SIZE",
    "GENERAL_STREAM_TYPES",
    "MAX_PAGE_SIZE",
    "MAX_WAIT_SECONDS",
    "READ_EVENT_LOG",
    "READ_FULL_EVENT_LOG",
    "register_event_log_route",
]
