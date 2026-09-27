"""Compose the Counsel handlers from the process-wide dependencies.

`wire_counsel(deps)` runs once during startup and the bundle it returns is
attached to the app. Routes and MCP tools both pull their handler out of
that bundle, which is what keeps the two surfaces calling the same code
rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   making a second record
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

Three slices take the middle layer, and the third is not a genesis.
Making a proposal and making an inquiry both mint an id on the server, so
a retry with no key would leave a second record of one act. Adopting
takes it for a sharper reason: a retry that the domain refuses would
already have dispatched an execution on the first attempt, and the caller
that could not tell whether its request landed needs the same execution
id back rather than a 409 it has to go and interpret.

Every other transition goes without, because a replayed one is refused by
the domain and the wrapper would buy a friendlier status code rather than
prevent a duplicate. The reads go without because there is nothing in a
read to make idempotent.

Two slices take more than the kernel. Each listing reads a projection,
which the kernel cannot hold because the kernel is declared in
infrastructure and these summaries are Counsel's own ideas, so this module
picks the implementations and passes them in.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.counsel.adapters import (
    InMemoryInquirySummaryLookup,
    InMemoryProposalSummaryLookup,
    PostgresInquirySummaryLookup,
    PostgresProposalSummaryLookup,
)
from keeper.counsel.aggregates.inquiry.summary import InquirySummaryLookup
from keeper.counsel.aggregates.proposal.summary import ProposalSummaryLookup
from keeper.counsel.features import (
    adopt_proposal,
    answer_inquiry,
    claim_inquiry,
    get_inquiry,
    get_proposal,
    list_inquiries,
    list_proposals,
    make_inquiry,
    make_proposal,
    take_proposal,
)
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel, UnreadableSummariesError
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "counsel"


@dataclass(frozen=True)
class CounselHandlers:
    """The bundle, one field per slice."""

    make_proposal: make_proposal.IdempotentHandler
    get_proposal: get_proposal.Handler
    take_proposal: take_proposal.Handler
    adopt_proposal: adopt_proposal.IdempotentHandler
    list_proposals: list_proposals.Handler
    make_inquiry: make_inquiry.IdempotentHandler
    claim_inquiry: claim_inquiry.Handler
    answer_inquiry: answer_inquiry.Handler
    get_inquiry: get_inquiry.Handler
    list_inquiries: list_inquiries.Handler


def _proposal_summary_lookup(deps: Kernel) -> ProposalSummaryLookup:
    """Pick the read adapter this deployment can actually use.

    With a pool, the projection table, which a background worker keeps in
    step. Without one, a fold over every proposal stream, because the worker
    does not run when there is nothing to project into and an empty table
    would answer "nothing is open" while proposals wait.
    """
    if deps.pool is not None:
        return PostgresProposalSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryProposalSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _inquiry_summary_lookup(deps: Kernel) -> InquirySummaryLookup:
    """Pick the read adapter this deployment can actually use.

    The same choice its sibling above makes, on the same test, and the two
    are deliberately separate functions rather than one generic picker. They
    return different ports, and the pair that would make them one is a
    protocol over both, which buys nothing and costs the reader the ability
    to see which table is being chosen.
    """
    if deps.pool is not None:
        return PostgresInquirySummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryInquirySummaryLookup(deps.event_store)
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
        adopt_proposal=with_tracing(
            with_idempotency(
                adopt_proposal.bind(deps),
                deps.idempotency_store,
                command_name="AdoptProposal",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="AdoptProposal",
            bc=_BC,
        ),
        list_proposals=with_tracing(
            list_proposals.bind(deps, _proposal_summary_lookup(deps)),
            command_name="ListProposals",
            bc=_BC,
        ),
        make_inquiry=with_tracing(
            with_idempotency(
                make_inquiry.bind(deps),
                deps.idempotency_store,
                command_name="MakeInquiry",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="MakeInquiry",
            bc=_BC,
        ),
        claim_inquiry=with_tracing(
            claim_inquiry.bind(deps),
            command_name="ClaimInquiry",
            bc=_BC,
        ),
        answer_inquiry=with_tracing(
            answer_inquiry.bind(deps),
            command_name="AnswerInquiry",
            bc=_BC,
        ),
        get_inquiry=with_tracing(
            get_inquiry.bind(deps),
            command_name="GetInquiry",
            bc=_BC,
        ),
        list_inquiries=with_tracing(
            list_inquiries.bind(deps, _inquiry_summary_lookup(deps)),
            command_name="ListInquiries",
            bc=_BC,
        ),
    )


__all__ = ["CounselHandlers", "wire_counsel"]
