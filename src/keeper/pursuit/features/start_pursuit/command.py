"""The intent: authorize a bounded loop toward a goal."""

from dataclasses import dataclass

from keeper.pursuit.aggregates.pursuit import Budget, PursuitBeamline, PursuitGoal


@dataclass(frozen=True)
class StartPursuit:
    """Authorize work toward this goal, at this beamline, over these scopes, within this budget.

    Every field is the caller's and every field is load-bearing. This is
    the one place a person states what a machine may then do without being
    asked again, so there is nothing here that could sensibly be defaulted:
    a beamline this system picked, a scope list it inferred or a budget it
    made up would each be the system authorizing itself.

    `goal`, `beamline` and `budget` arrive as their value objects rather
    than as loose primitives, so a caller cannot hand over a goal that is
    too long or a budget that bounds nothing and have it refused three
    layers in. `scopes` arrives as a tuple of strings, because the thing
    being bounded is the tuple and not any one member, and the decider is
    where it is checked, which is where Execution checks the same shape.

    **There is no `occurred_at`, and the absence is the point.**
    Authorizing is a speech act, and a speech act happens where it is
    spoken. There is no earlier moment out in the world for this record to
    be late to, so the moment this system writes one is the moment it
    happened. That is R8 landing on the makes side, beside `make_inquiry`.

    The pursuit id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.

    Who is authorizing is not here either. It is the authenticated
    principal, written by the handler, for the reason a proposal's proposer
    is not a field a caller fills in.
    """

    goal: PursuitGoal
    beamline: PursuitBeamline
    scopes: tuple[str, ...]
    budget: Budget


__all__ = ["StartPursuit"]
