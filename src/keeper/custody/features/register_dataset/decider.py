"""The decision: what registering a dataset produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to fetch and nothing to
invent.

There is no context module beside this one, and the absence is worth a
sentence because the nearest slice in the tree has one. `define_procedure`
loads plans because its decision needs their SCHEMAS: an acquisition's
parameters are checked against them, so sibling state is an input to the
decision.
This decision needs nothing from the execution. That the execution holds
the step is checked, but existence is the handler's to check and state is
the decider's, which
is the split docs/reference/patterns.md draws between a 404 and a
refusal. A context holder carrying a value nothing reads would be a door
held open for nobody.
"""

from datetime import datetime
from uuid import UUID

from keeper.custody.aggregates.dataset import (
    Dataset,
    DatasetAlreadyExistsError,
    DatasetRegistered,
)
from keeper.custody.features.register_dataset.command import RegisterDataset


def decide(
    state: Dataset | None,
    command: RegisterDataset,
    *,
    now: datetime,
    new_id: UUID,
) -> list[DatasetRegistered]:
    """Decide the events produced by registering a dataset.

    Invariants:
      - State must be None, or the id already has a history
        -> DatasetAlreadyExistsError

    One invariant, which is the honest count. This context holds a
    reference to something it cannot read, so there is nothing here to
    check it against: no shape to validate, no size to compare, no way to
    ask whether the address resolves. What can be refused is refused
    earlier, by `Identifier` when the pair is built and by the handler
    when the execution is loaded.

    What is NOT checked is whether some other dataset already names this
    same reference, or whether this step already has one. Nothing here can
    see another stream, and closing either would need a cross-stream
    pattern rather than a rule in this function. A producer sending the
    same registration twice is covered by the idempotency key instead,
    which is keyed on what it sent rather than on what it means.
    """
    if state is not None:
        raise DatasetAlreadyExistsError(state.id)
    return [
        DatasetRegistered(
            dataset_id=new_id,
            execution_id=command.execution_id,
            step_id=command.step_id,
            external_ref_scheme=command.external_ref.scheme,
            external_ref_value=command.external_ref.value,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
