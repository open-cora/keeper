"""The intent: tell this system where an acquisition's output ended up."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.identifier import Identifier
from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class RegisterDataset:
    """Register that one acquisition produced this data, held over there.

    Register, not deposit and not write. This system did not put the data
    anywhere and could not; something else did, and this command enrols
    the result. The glossary's genesis test is the check: "register a
    dataset" sounds like filing something that came from elsewhere, and
    "define a dataset" sounds like inventing data.

    The data is attached to one step of one execution, not to the
    execution as a whole. An execution may acquire several times and each
    acquisition writes its own data, so a reference to the traversal
    alone would lose which acquisition made which, and at a tomography
    beamline that is the sample position.

    Both ids, because `step_id` is enough to look a step up and not
    enough to check one. A step lives inside the Execution aggregate
    rather than on a stream of its own, so establishing that it exists
    means loading the execution that holds it.

    `external_ref` arrives as the value object rather than as two loose
    strings, so a caller cannot hand over half a reference. Building it
    is where a malformed scheme or value is refused, which is at the edge
    that received them.

    `occurred_at` is when the data was written, as the caller reports it,
    and a caller who omits it gets the moment the report arrived. A store
    that keeps the engine's own timestamps can supply the real one, and a
    backfill out of an archive would otherwise record every dataset as
    having appeared on the afternoon somebody ran the import.

    The dataset id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.
    """

    execution_id: UUID
    step_id: UUID
    external_ref: Identifier
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        The helper was Execution's when this slice was written, borrowed
        through the cross-context door. A third consumer met the rule of
        three in docs/reference/layout.md and it moved to
        `keeper.shared.instant`, so this is now an ordinary shared import
        and the door is one name narrower.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["RegisterDataset"]
