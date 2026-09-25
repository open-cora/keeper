"""The intent: record how one step of an execution ended."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.execution import StepOutcome
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ReportExecutionStep:
    """Record that step `index` of this execution ended this way.

    Carries the execution id because it names an execution that already exists
    rather than asking for a new one, and the index because a step has
    no id of its own: its place in the list the genesis fixed is what
    identifies it.

    `outcome` chooses which event this produces, and the three fields
    after it are the details each outcome carries. Exactly one grouping
    is well-formed per outcome, and a report that mixes them is refused
    rather than trimmed. That check belongs to the decider, where a
    caller learns it at the moment it reports.

    The command carries a discriminator where the events do not, and
    that asymmetry is the point rather than an inconsistency. A command
    is a request that can be refused, so a wrong field costs a 400. An
    event is a row nobody can edit, so the distinction moves onto the
    class where there is no field to get wrong.

    `occurred_at` is when the step ended, as the caller reports it. A
    caller who omits it gets the moment the report arrived, which for a
    execution reporting steps as they happen is close enough to be the usual
    case.
    """

    execution_id: UUID
    index: int
    outcome: StepOutcome
    engine_reference: str | None = None
    cause: str | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ReportExecutionStep"]
