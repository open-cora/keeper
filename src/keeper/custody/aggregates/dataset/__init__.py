"""The Dataset aggregate: state, events, evolver, and its read path."""

from keeper.custody.aggregates.dataset.events import (
    DatasetAddressRegistered,
    DatasetAddressWithdrawn,
    DatasetEvent,
    DatasetFindingRecorded,
    DatasetManifestRegistered,
    DatasetRegistered,
    from_stored,
    to_payload,
)
from keeper.custody.aggregates.dataset.evolver import (
    DatasetStreamOutOfOrderError,
    evolve,
    fold,
)
from keeper.custody.aggregates.dataset.finding import (
    DATASET_MAX_FINDINGS,
    FINDING_JUDGEMENT_MAX_LENGTH,
    Finding,
    InvalidFindingError,
)
from keeper.custody.aggregates.dataset.manifest import (
    ENTRY_PATH_MAX_LENGTH,
    MANIFEST_LABEL_MAX_LENGTH,
    MANIFEST_MAX_ENTRIES,
    Description,
    Entry,
    Extent,
    InvalidManifestError,
    Manifest,
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
    DatasetDescriptionUnchangedError,
    DatasetFindingsFullError,
    DatasetFindingUnchangedError,
    DatasetNotFoundError,
)

__all__ = [
    "DATASET_MAX_FINDINGS",
    "DATASET_STREAM_TYPE",
    "ENTRY_PATH_MAX_LENGTH",
    "FINDING_JUDGEMENT_MAX_LENGTH",
    "MANIFEST_LABEL_MAX_LENGTH",
    "MANIFEST_MAX_ENTRIES",
    "CopiedBy",
    "Dataset",
    "DatasetAddressKnownError",
    "DatasetAddressRegistered",
    "DatasetAddressUnknownError",
    "DatasetAddressWithdrawn",
    "DatasetAlreadyExistsError",
    "DatasetDescriptionUnchangedError",
    "DatasetEvent",
    "DatasetFindingRecorded",
    "DatasetFindingUnchangedError",
    "DatasetFindingsFullError",
    "DatasetManifestRegistered",
    "DatasetNotFoundError",
    "DatasetRegistered",
    "DatasetStreamOutOfOrderError",
    "Description",
    "Entry",
    "Extent",
    "Finding",
    "InvalidFindingError",
    "InvalidManifestError",
    "Manifest",
    "evolve",
    "fold",
    "from_stored",
    "load_dataset",
    "load_dataset_with_version",
    "to_payload",
]
