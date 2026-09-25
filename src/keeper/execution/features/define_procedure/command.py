"""The intent: define a procedure."""

from dataclasses import dataclass

from keeper.execution.aggregates.procedure import ProcedureStep


@dataclass(frozen=True)
class DefineProcedure:
    """Compose a routine out of moves and acquisitions, in this order.

    Both fields are the caller's and the id is not: the new procedure id,
    the timestamp and the correlation id all come from the handler's
    ports, so the decision this command produces is reproducible on
    replay.

    `name` and `beamline` are plain strings here rather than the value
    objects the state holds. The decider is where they become ones, so
    that the refusal of a bad one is listed with the slice's other
    refusals instead of being raised somewhere up at the edge by whoever
    built the command.

    `beamline` is the caller's because nothing here can derive it. The
    steps imply it, in a prefix this system deliberately does not parse,
    so the composer states it.

    `steps` arrives as the step union rather than as raw dictionaries,
    because the two surfaces above already have to parse the caller's
    JSON into something and a command holding dictionaries would make
    every reader of the decider parse them again.
    """

    name: str
    beamline: str
    steps: tuple[ProcedureStep, ...]


__all__ = ["DefineProcedure"]
