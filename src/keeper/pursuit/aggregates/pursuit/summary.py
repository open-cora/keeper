"""One pursuit as a list shows it, and the port that reads a page of them.

A pursuit is found by id when somebody already has the id. The question
this answers is the other one: which loops are turning at my beamline, and
which of them is waiting for me.

Both halves of that are operational rather than idle curiosity. A pursuit
authorizes a machine to dispatch work at a beamline without asking again,
so somebody standing at that beamline needs to be able to see every one
that can, and a held pursuit is a loop that has stopped and said why. A
list is how either is found, and until there is one the only way to know a
pursuit exists is to have been told its id.

## Why a port rather than a pool

The rows live in `proj_pursuit_pursuit_summary`, a table a background
worker maintains. A handler could read it through the kernel's connection
pool, and that does not work for the reason the sibling read models found
first: the MCP surface contract requires every published tool to be called
successfully in a walk, and those walks boot the application with
in-memory adapters and no database. A tool that refuses because there is
no pool fails the walk, and one answering "nothing is running" while loops
run is worse, because it is wrong rather than unavailable.

## Why the status is a column here and was derived next door

An inquiry's three states are written into two nullable timestamps,
because they only ever go one way: claimed then answered, and never back.
A pursuit's do go back. Held becomes Running when somebody resumes it, and
may become Held again on the next round, so a pair of timestamps would
have to record the last of an unbounded sequence rather than whether
something happened.

So the status is stored, and the projection writes it from whichever event
landed. That is the one place this read model can drift from the fold,
which is exactly why both sides answer one port contract suite and neither
can see the other.

## What is deliberately not on the row

**The budget and what has been spent against it.** Five numbers against
five limits, and one of the five depends on the clock at the moment of
asking, so a row could not hold it and a page of fifty would be mostly
arithmetic. The single read gives all of it, and the list exists to find
the pursuit rather than to report on it.

**The rounds.** A pursuit accumulates them without bound and a list that
carried them would grow without bound with it. `round_count` is the part a
reader scanning a page actually uses, and it is one integer.

**The scopes.** They belong to the authorization rather than to finding
one, and a caller narrowing a list by what a loop may drive is asking a
question nothing has asked yet.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.pursuit.aggregates.pursuit.state import PursuitStatus, RoundOutcome


@dataclass(frozen=True)
class PursuitSummary:
    """A pursuit as a list shows it.

    `goal` is on the row for the reason an inquiry's objective is: a list
    of loops with the goals taken out is a list of identifiers, and nobody
    scanning for the one they care about can use it. It is bounded so that
    it can ride here.

    `held_for` is set only while the status is Held, exactly as on the
    aggregate, because the null IS part of the status and a list that
    invented a second word for it would be a second spelling of one fact.

    `round_count` is how many rounds the pursuit has opened, closed or not.
    It is the cheap half of how far a loop has got, and the expensive half
    is the budget, which is not here.

    `created_at` and `stopped_at` are both this system's own clock. Every
    event this row is built from is on the makes side of R8, so there is no
    caller's moment anywhere on it, which is what keeps it different from
    an inquiry's three timestamps from two authorities.
    """

    pursuit_id: UUID
    actor_id: UUID
    goal: str
    beamline: str
    status: PursuitStatus
    held_for: RoundOutcome | None
    round_count: int
    created_at: datetime
    stopped_at: datetime | None


@dataclass(frozen=True)
class PursuitSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[PursuitSummary]
    next_cursor: str | None


class PursuitSummaryLookup(Protocol):
    """Read pursuits by something other than their id.

    Named `Lookup` because that is the shape this repository declares for a
    read port, in `test_port_naming_conventions.py`.
    """

    async def list_pursuits(
        self,
        *,
        status: PursuitStatus | None,
        beamline: str | None,
        limit: int,
        cursor: str | None,
    ) -> PursuitSummaryPage:
        """Return one page of pursuits, newest first.

        `status` narrows to one of the three, and None asks for every
        pursuit. Narrowing to Held is the triage question: which loops have
        stopped and are waiting for a person.

        `beamline` narrows to one beamline, and None asks across all of
        them. It is here where a proposal's list has no such filter,
        because a pursuit names a beamline in a way a proposal does not:
        somebody standing at one needs to see what may dispatch there
        without paging through every other beamline in the facility. It is
        the same question the work intake asks of executions.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["PursuitSummary", "PursuitSummaryLookup", "PursuitSummaryPage"]
