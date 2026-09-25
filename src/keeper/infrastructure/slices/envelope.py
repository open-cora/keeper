"""Cross-BC builder that wraps a domain event in the persistence envelope.

`to_new_event(...)` returns a `NewEvent` ready for `EventStore.append`.
Lives at `keeper/infrastructure/` (not in any single BC) because the
envelope shape (`event_id` + discriminator + `schema_version` +
`occurred_at` + correlation/causation + `metadata={"command": ...}`)
is the cross-BC persistence contract. Only the discriminator string
and the payload dict differ per aggregate, and the caller already
holds those.

Extracted from the per-aggregate `events.py` modules once a third
byte-identical copy appeared. Each aggregate's
`events.py` now owns just the genuinely aggregate-specific pieces:
the event classes, the `<Aggregate>Event` union, `to_payload`, and
`from_stored`. Handlers wire the two together at the persistence step,
reading the discriminator off the event class itself:

    new_events = [
        to_new_event(
            event_type=type(event).__name__,
            payload=to_payload(event),
            occurred_at=event.occurred_at,
            event_id=deps.id_generator.new_id(),
            command_name=_COMMAND_NAME,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        for event in domain_events
    ]

`metadata` is hardcoded to `{"command": command_name}` for now :
that's the only field every BC's handlers populate today. When a BC
wants to add a metadata field (eg. saga step id, source actor id),
either add it as a kwarg here or pass an explicit `metadata` dict
that this function merges with `command`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from keeper.infrastructure.ports import NewEvent

__all__ = ["to_new_event"]


def to_new_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    event_id: UUID,
    command_name: str,
    correlation_id: UUID,
    principal_id: UUID,
    causation_id: UUID | None = None,
    schema_version: int = 1,
) -> NewEvent:
    """Build a `NewEvent` envelope from a per-aggregate (event_type, payload).

    Caller supplies `event_type` (the discriminator string, which every
    handler here reads as `type(event).__name__`) and `payload` (the dict
    from `to_payload(event)`); this function adds the cross-BC envelope
    fields and returns the `NewEvent` ready to hand to
    `EventStore.append`. `schema_version` defaults to `1`; bump only
    when the schema-evolution policy in CONTRIBUTING.md forces it.

    `principal_id` carries the UUID of the entity that pulled the
    trigger for the command that produced this event (the same value
    the handler received as its `principal_id` kwarg). Required by
    the day-1 ReBAC hook, contract-enforced at the application layer
    (the `events.principal_id` DB column stays nullable so historical
    pre-hook rows remain valid). Day-1 hook for the future ReBAC
    graph projection.
    """
    return NewEvent(
        event_id=event_id,
        event_type=event_type,
        schema_version=schema_version,
        payload=payload,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata={"command": command_name},
        principal_id=principal_id,
    )
