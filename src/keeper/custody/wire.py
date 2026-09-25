"""Compose the Custody handlers from the process-wide dependencies.

`wire_custody(deps)` runs once during startup and the bundle it returns is
attached to the app. Routes and MCP tools both pull their handler out of
that bundle, which is what keeps the two surfaces calling the same code
rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   registering the same data twice
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

The two reads go without the middle layer, because a read has nothing to
make idempotent. Tracing wraps all three, because a query that is slow or
failing is as much a fact about the system as a write that is, and the
one read that goes to a table rather than to a stream is the one most
likely to become the slow one.

Registering a dataset takes the idempotency wrapper for the same reason
reporting a run does: the server mints the id, so a retry with no key
would leave a second record of one thing. That matters more here than it
looks. Nothing in this context refuses a duplicate on its own, because
one stream cannot see another, so the key is the only thing standing
between a redelivered report and two records of one body of data. A
producer that derives its key from the store's own address for the data
recomputes it after any restart having persisted nothing, which is what
makes at-least-once delivery safe.

One slice takes more than the kernel. `list_datasets` reads a projection,
which the kernel cannot hold because the kernel is declared in
infrastructure and a dataset summary is Custody's own idea, so this
module picks the implementation and passes it in.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.custody.adapters import (
    InMemoryDatasetSummaryLookup,
    PostgresDatasetSummaryLookup,
)
from keeper.custody.aggregates.dataset.summary import DatasetSummaryLookup
from keeper.custody.features import get_dataset, list_datasets, register_dataset
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "custody"


class UnreadableSummariesError(RuntimeError):
    """Startup found no way to read this context's summaries.

    Raised when there is neither a connection pool nor the in-memory event
    store, which is a combination no supported environment produces and a
    new adapter could. Failing here rather than at the first request is
    the point: a deployment that cannot answer a query should not finish
    booting and look healthy.
    """

    def __init__(self, event_store: str) -> None:
        super().__init__(
            f"No pool and no in-memory event store ({event_store}), so nothing "
            "can answer a summary query"
        )
        self.event_store = event_store


@dataclass(frozen=True)
class CustodyHandlers:
    """The bundle, one field per slice."""

    register_dataset: register_dataset.IdempotentHandler
    get_dataset: get_dataset.Handler
    list_datasets: list_datasets.Handler


def _dataset_summary_lookup(deps: Kernel) -> DatasetSummaryLookup:
    """Pick the read adapter this deployment can actually use.

    With a pool, the projection table, which a background worker keeps in
    step. Without one, a fold over every dataset stream, because the
    worker does not run when there is nothing to project into and an
    empty table would answer "no datasets" while datasets exist.
    """
    if deps.pool is not None:
        return PostgresDatasetSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryDatasetSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def wire_custody(deps: Kernel) -> CustodyHandlers:
    """Build the Custody handlers."""
    return CustodyHandlers(
        register_dataset=with_tracing(
            with_idempotency(
                register_dataset.bind(deps),
                deps.idempotency_store,
                command_name="RegisterDataset",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="RegisterDataset",
            bc=_BC,
        ),
        get_dataset=with_tracing(
            get_dataset.bind(deps),
            command_name="GetDataset",
            bc=_BC,
        ),
        list_datasets=with_tracing(
            list_datasets.bind(deps, _dataset_summary_lookup(deps)),
            command_name="ListDatasets",
            bc=_BC,
        ),
    )


__all__ = ["CustodyHandlers", "UnreadableSummariesError", "wire_custody"]
