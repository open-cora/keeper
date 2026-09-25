"""Compose the Counsel handlers from the process-wide dependencies.

`wire_counsel(deps)` runs once during startup and the bundle it returns
is attached to the app. Routes and MCP tools both pull their handler out
of that bundle, which is what keeps the two surfaces calling the same
code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   making a second proposal
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

Only the genesis takes the middle layer. Making a proposal mints an id
on the server, so a retry with no key would leave a second record of one
piece of advice. Taking one goes without, because a replayed take is
already refused by the domain and the wrapper would buy a friendlier
status code rather than prevent a duplicate. The two reads go without
because there is nothing in a read to make idempotent.

One slice takes more than the kernel. `list_proposals` reads a
projection, which the kernel cannot hold because the kernel is declared
in infrastructure and a proposal summary is Counsel's own idea, so this
module picks the implementation and passes it in.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.counsel.adapters import (
    InMemoryProposalSummaryLookup,
    PostgresProposalSummaryLookup,
)
from keeper.counsel.aggregates.proposal.summary import ProposalSummaryLookup
from keeper.counsel.features import (
    get_proposal,
    list_proposals,
    make_proposal,
    take_proposal,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "counsel"


class UnreadableSummariesError(RuntimeError):
    """Startup found no way to read this context's summaries.

    Raised when there is neither a connection pool nor the in-memory
    event store, which is a combination no supported environment
    produces and a new adapter could. Failing here rather than at the
    first request is the point: a deployment that cannot answer a query
    should not finish booting and look healthy.

    The third class with this name and this body, one per context that
    has a read model. Its siblings said the next one to need it is the
    trigger to hoist, and this is that one. Still not hoisted here, for
    the reason they gave: a landing that adds a read model should not
    also reshape the two beside it. The move is its own commit, and it
    is now overdue alongside `UnauthorizedError`.
    """

    def __init__(self, event_store: str) -> None:
        super().__init__(
            f"No pool and no in-memory event store ({event_store}), so nothing "
            "can answer a summary query"
        )
        self.event_store = event_store


@dataclass(frozen=True)
class CounselHandlers:
    """The bundle, one field per slice."""

    make_proposal: make_proposal.IdempotentHandler
    get_proposal: get_proposal.Handler
    take_proposal: take_proposal.Handler
    list_proposals: list_proposals.Handler


def _proposal_summary_lookup(deps: Kernel) -> ProposalSummaryLookup:
    """Pick the read adapter this deployment can actually use.

    With a pool, the projection table, which a background worker keeps
    in step. Without one, a fold over every proposal stream, because the
    worker does not run when there is nothing to project into and an
    empty table would answer "nothing is open" while proposals wait.
    """
    if deps.pool is not None:
        return PostgresProposalSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryProposalSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def wire_counsel(deps: Kernel) -> CounselHandlers:
    """Build the Counsel handlers."""
    return CounselHandlers(
        make_proposal=with_tracing(
            with_idempotency(
                make_proposal.bind(deps),
                deps.idempotency_store,
                command_name="MakeProposal",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="MakeProposal",
            bc=_BC,
        ),
        get_proposal=with_tracing(
            get_proposal.bind(deps),
            command_name="GetProposal",
            bc=_BC,
        ),
        take_proposal=with_tracing(
            take_proposal.bind(deps),
            command_name="TakeProposal",
            bc=_BC,
        ),
        list_proposals=with_tracing(
            list_proposals.bind(deps, _proposal_summary_lookup(deps)),
            command_name="ListProposals",
            bc=_BC,
        ),
    )


__all__ = ["CounselHandlers", "UnreadableSummariesError", "wire_counsel"]
