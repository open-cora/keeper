"""The decision: what recording a finding about a dataset produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.custody.aggregates.dataset import (
    DATASET_MAX_FINDINGS,
    Dataset,
    DatasetFindingRecorded,
    DatasetFindingsFullError,
    DatasetFindingUnchangedError,
    DatasetNotFoundError,
)
from keeper.custody.features.record_dataset_finding.command import RecordDatasetFinding


def decide(
    state: Dataset | None,
    command: RecordDatasetFinding,
    *,
    now: datetime,
) -> list[DatasetFindingRecorded]:
    """Decide the events produced by recording a finding.

    Invariants:
      - State must not be None, or no such dataset was registered
        -> DatasetNotFoundError
      - The finding must say something the record does not
        -> DatasetFindingUnchangedError
      - A new judgement must fit within what one dataset may carry
        -> DatasetFindingsFullError

    **No address is checked, and none is carried.** The description
    slice refuses a copy this record never heard of, because something
    opened a file and said which. Nothing opened anything here. A
    finding is reached from what this record already holds, so there is
    no copy whose reading could have differed and nothing to check an
    address against.

    **A repeat of the same judgement on different counts is admitted.**
    This is the same call the description makes and rests on the same
    fact: the shapes a finding was drawn from can change under it, so a
    second look reaching the same word with different numbers has
    something new to say. What is refused is the identical conclusion
    arriving twice, which is at-least-once delivery rather than news.

    **The bound counts judgements, not recordings.** Replacing one the
    record already carries adds none, so a computation that keeps
    looking never reaches the limit. Only a caller inventing a new word
    each time does, and that is a caller using the judgement as a key
    for something it was not meant to key.

    What is NOT checked is whether the judgement is true, whether the
    counts support it, or whether a later finding is better than an
    earlier one. Nothing here can reach the data, which is the posture
    of this whole context, and nothing here knows where a computation
    got its expectation.
    """
    if state is None:
        raise DatasetNotFoundError(command.dataset_id)
    offered = command.finding
    if offered in state.findings:
        raise DatasetFindingUnchangedError(state.id, offered.judgement)
    standing = {held.judgement for held in state.findings}
    if offered.judgement not in standing and len(standing) >= DATASET_MAX_FINDINGS:
        raise DatasetFindingsFullError(state.id, DATASET_MAX_FINDINGS)
    return [
        DatasetFindingRecorded(
            dataset_id=command.dataset_id,
            judgement=offered.judgement,
            expected=offered.expected,
            arrived=offered.arrived,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
