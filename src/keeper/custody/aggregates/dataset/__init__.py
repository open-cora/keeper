"""The Dataset aggregate: state, events, evolver, and its read path."""

from keeper.custody.aggregates.dataset.events import (
    DatasetEvent,
    DatasetRegistered,
    DatasetReplicated,
    DatasetWithdrawn,
    from_stored,
    to_payload,
)
from keeper.custody.aggregates.dataset.evolver import (
    DatasetStreamOutOfOrderError,
    evolve,
    fold,
)
from keeper.custody.aggregates.dataset.read import DATASET_STREAM_TYPE, load_dataset
from keeper.custody.aggregates.dataset.state import (
    Dataset,
    DatasetAddressKnownError,
    DatasetAddressUnknownError,
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
)

__all__ = [
    "DATASET_STREAM_TYPE",
    "Dataset",
    "DatasetAddressKnownError",
    "DatasetAddressUnknownError",
    "DatasetAlreadyExistsError",
    "DatasetEvent",
    "DatasetNotFoundError",
    "DatasetRegistered",
    "DatasetReplicated",
    "DatasetStreamOutOfOrderError",
    "DatasetWithdrawn",
    "evolve",
    "fold",
    "from_stored",
    "load_dataset",
    "to_payload",
]
