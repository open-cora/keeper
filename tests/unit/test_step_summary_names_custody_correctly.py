"""The two strings that reach across into Custody name what is there.

`InMemoryStepSummaryLookup` reads Custody's dataset streams and the step
summary projection subscribes to Custody's dataset event. Neither
imports Custody and neither can: Custody already reaches into Execution
to check that a step exists before filing a dataset against one, so an
import the other way would close a cycle and `tach` would refuse it.

Naming a producer with a string is the sanctioned way across that line.
What it costs is that a rename over there leaves these behind, and the
failure is quiet in the worst way: the lookup finds no dataset streams,
concludes that nothing has ever been filed, and reports every run in
the facility as a gap. Every write still succeeds and every other test
still passes.

This is the one check that reads both sides. A test may import across
the line because `tach` excludes tests, which is what makes the
agreement checkable at all.
"""

import pytest

from keeper.custody.aggregates.dataset.events import DatasetRegistered
from keeper.custody.aggregates.dataset.read import DATASET_STREAM_TYPE
from keeper.execution.adapters.in_memory_step_summary_lookup import (
    DATASET_REGISTERED_EVENT_TYPE,
)
from keeper.execution.adapters.in_memory_step_summary_lookup import (
    DATASET_STREAM_TYPE as NAMED_STREAM_TYPE,
)
from keeper.execution.projections.step_summary import StepSummaryProjection

pytestmark = pytest.mark.unit


def test_the_fold_reads_the_stream_type_custody_actually_writes() -> None:
    assert NAMED_STREAM_TYPE == DATASET_STREAM_TYPE


def test_the_fold_reads_the_event_type_custody_actually_writes() -> None:
    """An event's type is its class name, which is what the store records."""
    assert DatasetRegistered.__name__ == DATASET_REGISTERED_EVENT_TYPE


def test_the_projection_subscribes_to_the_event_custody_actually_writes() -> None:
    """The other half of the pair, and the one that fills the column.

    A projection subscribed to a name nothing publishes leaves
    `dataset_id` null on every row, which reads as a facility that
    files nothing rather than as a broken subscription.
    """
    assert DatasetRegistered.__name__ in StepSummaryProjection.subscribed_event_types
