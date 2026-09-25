"""The intent: relay what an engine did to the run one step opened."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.execution import EngineReport
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ReportStepRun:
    """Say what the engine did to the run this step asked for.

    The second of two accounts of one step. `ReportExecutionStep` carries what
    the driver saw, which is that its call returned or raised. This
    carries what the engine said about itself, relayed by whatever
    watches that engine, and the two arrive from different clients on
    different schedules.

    One command with a discriminator rather than six, and six event
    classes rather than one with a field. That asymmetry is the same one
    `ReportExecutionStep` draws and is there for the same reason: a command is
    a request that can be refused, so a wrong value costs a 400, while an
    event is a row nobody can edit, so the distinction moves onto the
    class where there is no field to get wrong.

    `step_id` and not an index. A driver knows the position it is
    walking; whatever watches the engine knows only the id the driver
    carried into the engine's own metadata.

    `engine_reference` belongs to a start and to nothing else. It is what
    the engine calls this run, and it arrives here as well as on a done
    step because whichever of the two lands first is what lets anybody
    find the run.

    `occurred_at` is when the engine did it, as the caller reports it. A
    caller who omits it gets the moment the report arrived, and the gap
    matters most for a reporter draining an archive.
    """

    execution_id: UUID
    step_id: UUID
    reported: EngineReport
    engine_reference: str | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ReportStepRun"]
