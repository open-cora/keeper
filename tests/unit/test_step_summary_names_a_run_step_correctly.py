"""The word the projection looks for is the word a procedure writes.

`ProcedureDefined` renders each composed step with a `kind`, and the
step summary projection reads that word to decide whether driving the
step opens a run. The two are a string on each side, spelled in files
that never meet.

What a disagreement costs is the quietest failure this projection has.
Every step would record as a move, every run would be a step expected
to produce nothing, and the listing of runs whose data nothing recorded
would come back empty for a facility losing all of it. Nothing would
error, no write would fail, and the view would read as a clean bill of
health.

So the word is not compared against another constant, which would only
prove two files agree. A real run step is rendered through the
aggregate's own payload function, and the projection's word is checked
against what came out.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from keeper.execution.aggregates.procedure.events import ProcedureDefined, to_payload
from keeper.execution.aggregates.procedure.state import ComposedStep, RunStep, SetStep
from keeper.execution.projections.step_summary import RUN_KIND

pytestmark = pytest.mark.unit


def _rendered(step: RunStep | SetStep) -> str:
    event = ProcedureDefined(
        procedure_id=uuid4(),
        procedure_name="align_then_scan",
        beamline="2-bm",
        steps=(ComposedStep(id=uuid4(), step=step),),
        occurred_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
    )
    (only,) = to_payload(event)["steps"]
    return str(only["kind"])


def test_the_projection_reads_the_kind_a_stored_run_step_actually_carries() -> None:
    assert _rendered(RunStep(operation_id=uuid4(), scopes=("2bmb:m1",))) == RUN_KIND


def test_a_stored_move_does_not_carry_the_kind_the_projection_reads() -> None:
    assert _rendered(SetStep(record="2bmb:m1", to=0.0)) != RUN_KIND
