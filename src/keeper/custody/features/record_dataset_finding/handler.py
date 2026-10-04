"""Record a finding: authorize, load, decide, append.

Update-style, so this command names a stream that already has rows. The
handler folds that history before deciding and passes the version it
read back as `expected_version`.

That version is what keeps two computations from losing each other's
work. Both fold the same state, both decide to append at the same
version, and the store lets one through and raises `ConcurrencyError`
at the other, which surfaces as a 409. Without it the later append
could land out of order and the fold would keep whichever arrived
last as the record's answer for a judgement neither of them meant to
overwrite.

No execution is loaded. The genesis slice checks the run it names
exists, because the join is what it is adding. This one judges a record
whose join is already made and already checked.

No idempotency wrapper. The server mints nothing a caller could key a
retry on, and a replayed call is refused by the domain, so the wrapper
would buy a nicer status code for a retry rather than prevent a
duplicate. Every other update slice here is arranged the same way.
"""

from typing import Protocol
from uuid import UUID

from keeper.custody.aggregates.dataset import (
    DATASET_STREAM_TYPE,
    load_dataset_with_version,
    to_payload,
)
from keeper.custody.features.record_dataset_finding.command import RecordDatasetFinding
from keeper.custody.features.record_dataset_finding.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "RecordDatasetFinding"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: RecordDatasetFinding,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: RecordDatasetFinding,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "record_dataset_finding.denied",
                command_name=_COMMAND_NAME,
                dataset_id=str(command.dataset_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_dataset_with_version(deps.event_store, command.dataset_id)
        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            DATASET_STREAM_TYPE,
            command.dataset_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=deps.id_generator.new_id(),
                    command_name=_COMMAND_NAME,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    principal_id=principal_id,
                )
                for event in events
            ],
        )

        _log.info(
            "record_dataset_finding.success",
            command_name=_COMMAND_NAME,
            dataset_id=str(command.dataset_id),
            judgement=command.finding.judgement,
            expected=command.finding.expected,
            arrived=command.finding.arrived,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
