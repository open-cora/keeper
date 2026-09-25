"""One row per dataset, and the port that reads those rows.

The other read path, and here it is the important one. `read.py` rebuilds
one dataset by replaying its stream, which answers a question that already
names the dataset. The question this context exists for names an acquisition
and asks what came out of it, and folding cannot answer that: a fold has to
know which stream to fold, and that is exactly what is being asked.

So of the two reads in this context, the one that needs a maintained table
is the one carrying the purpose. `get_dataset` shipped first only because
it is the half a fold can serve.

## Why a port rather than a pool

The rows live in `proj_custody_dataset_summary`, a table a background
worker maintains. A handler could read it directly through the kernel's
connection pool, and that does not work here for the reason the sibling
context found first: the MCP surface contract requires every published
tool to be called successfully in a walk, and those walks boot the
application with in-memory adapters and no database. A tool that refuses
because there is no pool fails the execution, and one that answers "no
datasets" while datasets exist is worse, because it is wrong rather than
unavailable.

## What a summary leaves out, and why that is nothing

An execution summary drops its steps, because they are unbounded and a page
of fifty rows would be mostly parameters. A dataset has nothing to drop.
Every field on the record is either an id or half of a reference, so the
summary carries the whole aggregate and one timestamp. That is not an
oversight in either direction: it is what a context holding only a join
looks like from the read side.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.shared.identifier import Identifier


@dataclass(frozen=True)
class DatasetSummary:
    """A dataset as a list shows it.

    `created_at` is when the data was reported to have been written, not
    when the row was made. It is the domain time the caller supplied,
    taken from the envelope, so a backfill out of a store's own records
    says when the data actually appeared rather than when somebody ran
    the import.

    There is no `updated_at`, and the absence is the aggregate's rather
    than this row's. Nothing changes a dataset yet, so a second timestamp
    would always equal the first, and a column that can only ever agree
    with its neighbour says nothing while implying a lifecycle nobody
    wrote. It arrives with the first event that moves one.
    """

    dataset_id: UUID
    execution_id: UUID
    step_id: UUID
    external_ref: Identifier
    created_at: datetime


@dataclass(frozen=True)
class DatasetSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[DatasetSummary]
    next_cursor: str | None


class DatasetSummaryLookup(Protocol):
    """Read datasets by something other than their id.

    Named `Lookup` because that is the shape this repository declares for
    a read port, in `test_port_naming_conventions.py`.
    """

    async def list_datasets(
        self,
        *,
        step_id: UUID | None,
        limit: int,
        cursor: str | None,
    ) -> DatasetSummaryPage:
        """Return one page of datasets, newest first.

        `step_id` narrows to the datasets one acquisition produced,
        which is the question this context exists to answer. Filtering on
        the step and not on the execution is the whole point: an
        execution may acquire several times, and which acquisition made
        which data is the fact a reader needs.

        It is deliberately not guaranteed to match at most one: how many
        datasets an acquisition produces is the reporting side's policy
        and not a rule here, so this answers with however many there
        are.

        There is no filter on the external reference, because nothing
        asks. A producer wanting to know whether it already registered an
        address uses its idempotency key, which answers without a query;
        adding the filter before a caller needs it would be an index and
        a parameter maintained for nobody.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["DatasetSummary", "DatasetSummaryLookup", "DatasetSummaryPage"]
