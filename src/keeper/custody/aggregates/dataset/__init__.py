"""The Dataset aggregate: state, events, evolver, and its read path."""

from keeper.custody.aggregates.dataset.events import (
    DatasetAddressRegistered,
    DatasetAddressWithdrawn,
    DatasetEvent,
    DatasetRegistered,
    from_stored,
    to_payload,
)
from keeper.custody.aggregates.dataset.evolver import (
    DatasetStreamOutOfOrderError,
    evolve,
    fold,
)
from keeper.custody.aggregates.dataset.read import (
    DATASET_STREAM_TYPE,
    load_dataset,
    load_dataset_with_version,
)
from keeper.custody.aggregates.dataset.state import (
    CopiedBy,
    Dataset,
    DatasetAddressKnownError,
    DatasetAddressUnknownError,
    DatasetAlreadyExistsError,
    DatasetNotFoundError,
)

__all__ = [
    "DATASET_STREAM_TYPE",
    "CopiedBy",
    "Dataset",
    "DatasetAddressKnownError",
    "DatasetAddressRegistered",
    "DatasetAddressUnknownError",
    "DatasetAddressWithdrawn",
    "DatasetAlreadyExistsError",
    "DatasetEvent",
    "DatasetNotFoundError",
    "DatasetRegistered",
    "DatasetStreamOutOfOrderError",
    "evolve",
    "fold",
    "from_stored",
    "load_dataset",
    "load_dataset_with_version",
    "to_payload",
]
