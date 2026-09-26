"""The intent: put a question to a thinker about one execution."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class MakeInquiry:
    """Ask what should happen next, given this execution and this objective.

    Make, and it is the word this context already uses. Neither of the
    glossary's two genesis words fits, for the reason `make_proposal` gives:
    that pair was built for things that persist as specifications, and
    asking is an act. "Make an inquiry" is the phrase people say, which is
    what R1 in docs/reference/naming.md asks of a name.

    **There is no `occurred_at`.** Putting a question is a speech act, so
    the call IS the asking and there is no earlier moment for the record to
    be late to. The two commands that follow this one on the same stream do
    take one, because a thinker takes work up and concludes on its own
    clock. That is R8 running between three commands on one stream.

    **There is no asker either.** The handler writes the authenticated
    principal, so a caller controls who it asked as exactly as much as a
    caller of `make_proposal` controls who advised.

    **There is no step count.** The number of steps the execution has is
    read off the execution by the handler, because it is the denominator
    every later reading of the observation boundary is measured against and
    a caller that supplied its own could make a partial reading look
    complete.

    The inquiry id and the correlation id are not the caller's. They come
    from the handler's ports, so the decision this command produces is
    reproducible on replay.
    """

    execution_id: UUID
    objective: str


__all__ = ["MakeInquiry"]
