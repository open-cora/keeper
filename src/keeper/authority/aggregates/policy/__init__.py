"""The Policy aggregate: state, events, the fold, and how to load one."""

from keeper.authority.aggregates.policy.events import (
    PolicyDefined,
    PolicyEvent,
    PolicyPermissionGranted,
    PolicyPermissionRevoked,
    from_stored,
    to_payload,
)
from keeper.authority.aggregates.policy.evolver import evolve, fold
from keeper.authority.aggregates.policy.read import (
    POLICY_STREAM_TYPE,
    load_policy,
    load_policy_with_version,
)
from keeper.authority.aggregates.policy.state import (
    GOVERNING_COMMAND_NAMES,
    Permission,
    Policy,
    PolicyAlreadyExistsError,
    PolicyCannotGrantPermissionError,
    PolicyCannotRevokePermissionError,
    PolicyNotFoundError,
    PolicyWouldBeUngovernableError,
    SystemPrincipalCannotBeGrantedError,
    reject_an_ungovernable_policy,
    reject_the_system_principal,
    sorted_permissions,
    ungoverned_commands,
)

__all__ = [
    "GOVERNING_COMMAND_NAMES",
    "POLICY_STREAM_TYPE",
    "Permission",
    "Policy",
    "PolicyAlreadyExistsError",
    "PolicyCannotGrantPermissionError",
    "PolicyCannotRevokePermissionError",
    "PolicyDefined",
    "PolicyEvent",
    "PolicyNotFoundError",
    "PolicyPermissionGranted",
    "PolicyPermissionRevoked",
    "PolicyWouldBeUngovernableError",
    "SystemPrincipalCannotBeGrantedError",
    "evolve",
    "fold",
    "from_stored",
    "load_policy",
    "load_policy_with_version",
    "reject_an_ungovernable_policy",
    "reject_the_system_principal",
    "sorted_permissions",
    "to_payload",
    "ungoverned_commands",
]
