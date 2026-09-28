"""HTTP door for withdrawing a pursuit.

`POST /pursuits/{pursuit_id}/withdraw`, with no body.

A POST to a subresource rather than a DELETE on the pursuit, because
nothing is deleted. The pursuit stays on the record, the executions it
dispatched stay exactly as they are, and what changes is that it will
authorize nothing further. A DELETE would say the opposite of all three.

No body at all. The only thing a caller could put in one is a reason, and
this record declines to hold one: who withdrew it is on the envelope, and
asking that person is better than reading free text they typed in a hurry.

An `Idempotency-Key`, which no other transition in this tree takes. A 409
is the right answer to withdrawing a pursuit that somebody else already
stopped, and the wrong answer to a caller's own retry after a timeout;
only a key tells those two apart. Sent with one, a replayed withdrawal is
a second 204. Sent without, it meets the decider and is refused like any
other repeat.

204 rather than the pursuit back. A caller that wants the stopped record
can read it, and returning it here would make the common case pay for the
rare one.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.features.withdraw_pursuit.command import WithdrawPursuit
from keeper.pursuit.features.withdraw_pursuit.handler import IdempotentHandler


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.pursuit.withdraw_pursuit
    return handler


router = APIRouter(tags=["pursuit"])


@router.post(
    "/pursuits/{pursuit_id}/withdraw",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not withdraw pursuits.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No pursuit with that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The pursuit had already stopped.",
        },
    },
    summary="Withdraw a pursuit",
)
async def post_pursuit_withdrawal(
    pursuit_id: UUID,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Replay the same key to be told the withdrawal worked, "
                "rather than that it had already happened."
            ),
        ),
    ] = None,
) -> None:
    await handler(
        WithdrawPursuit(pursuit_id=pursuit_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
