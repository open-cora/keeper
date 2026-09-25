"""The sibling state this slice's decision needs, loaded before deciding.

The handler has already refused an execution with no stream behind it, a
step that execution does not hold, and a procedure that holds no such
composed step. What crosses here is the definition of the acquisition,
because the decision asks it one question: which plan it runs.

That is the difference from `register_dataset` next door, which makes
the first two of those checks and hands nothing across. Its decision
needs the step to exist and nothing more, so it has no context module at
all. This one compares, so the definition is an input.

## Why the definition rather than the execution's step

The step of the execution is what the proposal ends up pointing at, and
it is the wrong thing to read a plan off. It carries a sentence for a
reader, an id, and how the step went, and the id of the composed step it
was dispatched from. Everything about what the step was asked to do
lives on that composed step.

So the handler follows the reference and hands the definition over. The
alternative is a copy of the plan id on every execution's step, which is
what this held first: one field answering one consumer's one question,
with the next question needing the next field.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.procedure import ComposedStep


@dataclass(frozen=True)
class TakeProposalContext:
    """The composed step the recorded acquisition was dispatched from.

    Read at handler time, so it can be stale by the time the append
    lands. What this check is for is catching a caller that resolved the
    wrong step, not racing one being reported.

    Staler than it looks, and harmlessly so. A procedure has one event
    and nothing edits it, so what this holds cannot change at all once
    the definition exists.
    """

    composed: ComposedStep


__all__ = ["TakeProposalContext"]
