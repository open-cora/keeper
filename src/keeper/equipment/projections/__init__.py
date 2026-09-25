"""Read models for the Equipment bounded context."""

from keeper.equipment.projections.device_summary import (
    PROJECTION_NAME,
    DeviceSummaryProjection,
)
from keeper.equipment.projections.register import register_equipment_projections

__all__ = ["PROJECTION_NAME", "DeviceSummaryProjection", "register_equipment_projections"]
