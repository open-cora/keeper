"""The withdraw_dataset_address slice, re-exported so callers read `.bind`."""

from keeper.custody.features.withdraw_dataset_address.command import WithdrawDatasetAddress
from keeper.custody.features.withdraw_dataset_address.decider import decide
from keeper.custody.features.withdraw_dataset_address.handler import Handler, bind
from keeper.custody.features.withdraw_dataset_address.route import router

__all__ = [
    "Handler",
    "WithdrawDatasetAddress",
    "bind",
    "decide",
    "router",
]
