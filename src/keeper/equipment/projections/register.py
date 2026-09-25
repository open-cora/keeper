"""Hand Equipment's projections to the worker that advances them.

The composition root calls this once during startup, after
`wire_equipment` and before the worker starts. Mechanical by design: the
registry decides nothing, it holds what it is given, so everything
interesting about a projection is in the projection.

It lives inside the projections package rather than at the context root,
where the other three plug points are flat modules named for the call
(`wire.py`, `routes.py`, `tools.py`). The fourth cannot use the matching
name, because a module and a package cannot share one name inside a
package and the package is where the projections belong. See
docs/reference/layout.md.
"""

from keeper.equipment.projections.device_summary import DeviceSummaryProjection
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.projection.registry import ProjectionRegistry


def register_equipment_projections(registry: ProjectionRegistry, deps: Kernel) -> None:
    """Register every Equipment projection with the worker's registry.

    `deps` is unused today and is in the signature anyway, because the
    signature is the one every context implements and a projection that
    needs the clock or the id generator should not have to change the
    shape of this call to get them.

    `test_every_bc_is_mounted.py` checks that the composition root
    actually makes the call, which is the failure this would otherwise
    have: a projection that is written, tested, and never subscribed,
    leaving a read model empty while every write succeeds.
    """
    _ = deps
    registry.register(DeviceSummaryProjection())


__all__ = ["register_equipment_projections"]
