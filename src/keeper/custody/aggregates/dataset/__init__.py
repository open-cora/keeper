"""The Dataset aggregate: state, events, evolver, and its read path."""

from keeper.custody.aggregates.dataset.events import (
    DatasetEvent,
    DatasetRegistered,
    from_stored,
    to_payload,
)
from keeper.custody.aggregates.dataset.evolver import evolve, fold
from keeper.custody.aggregates.dataset.read import DATASET_STREAM_TYPE, load_dataset
from keeper.custody.aggregates.dataset.state import (
    Dataset,
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
)

__all__ = [
    "DATASET_STREAM_TYPE",
    "Dataset",
    "DatasetAlreadyExistsError",
    "DatasetEvent",
    "DatasetNotFoundError",
    "DatasetRegistered",
    "evolve",
    "fold",
    "from_stored",
    "load_dataset",
    "to_payload",
]
