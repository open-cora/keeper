"""Making, reading and taking a proposal over HTTP, through the real app.

The unit tests exercise the handlers directly, so neither they nor the
integration tier can see the two failures that live only on a route: a
request field bound to the wrong argument, and a domain error nobody
registered a status code for. Both leave every other tier green, and the
second is a 500.

That second one matters here, because this context registers four
handlers and relies on another context for four more. `PlanNotFoundError`,
`ExecutionNotFoundError`, `ExecutionStepNotFoundError` and
`InvalidOccurredAtError` all reach a Counsel route and none is registered
by Counsel. Whether that reliance holds is not something the source can
state, so it is walked below.

The proposer is the other thing only this tier can see. It is not a
request field, so no unit test of the route model would catch it being
dropped: it comes off the authenticated principal, and what proves it is
reading a proposal back and finding somebody named.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

_OPEN_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_TYPED_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_time_s": {"type": "number"}},
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def _a_plan(client: TestClient, schema: dict[str, Any] | None = None) -> str:
    response = client.post(
        "/plans",
        json={"name": "count", "parameters_schema": schema or _OPEN_SCHEMA},
    )
    assert response.status_code == 201, response.text
    plan_id: str = response.json()["plan_id"]
    return plan_id


def _an_acquisition_of(client: TestClient, plan_id: str) -> tuple[str, str]:
    """Compose a procedure that acquires with this plan and dispatch it.

    Three calls where a run took one, and all three are load bearing.
    There is no way to make a step without a procedure holding it and an
    execution dispatching that procedure, which is the whole content of
    AROC owning the genesis.
    """
    defined = client.post(
        "/procedures",
        json={
            "name": "align_then_scan",
            "beamline": "2-bm",
            "steps": [
                {"kind": "move", "record": "2bmb:m1", "to": 0.0},
                {
                    "kind": "acquire",
                    "plan_id": plan_id,
                    "parameters": {},
                    "scopes": ["2bmb:det:"],
                },
            ],
        },
    )
    assert defined.status_code == 201, defined.text
    dispatched = client.post("/executions", json={"procedure_id": defined.json()["procedure_id"]})
    assert dispatched.status_code == 201, dispatched.text
    execution_id: str = dispatched.json()["execution_id"]
    read = client.get(f"/executions/{execution_id}")
    assert read.status_code == 200, read.text
    step_id: str = read.json()["steps"][1]["step_id"]
    return execution_id, step_id


def _a_move_in(client: TestClient) -> tuple[str, str]:
    """A dispatched step that runs no plan."""
    defined = client.post(
        "/procedures",
        json={
            "name": "park",
            "beamline": "2-bm",
            "steps": [{"kind": "move", "record": "2bmb:m1", "to": 0.0}],
        },
    )
    assert defined.status_code == 201, defined.text
    dispatched = client.post("/executions", json={"procedure_id": defined.json()["procedure_id"]})
    assert dispatched.status_code == 201, dispatched.text
    execution_id: str = dispatched.json()["execution_id"]
    read = client.get(f"/executions/{execution_id}")
    step_id: str = read.json()["steps"][0]["step_id"]
    return execution_id, step_id


def _body(acquisition: tuple[str, str], **extra: str) -> dict[str, str]:
    execution_id, step_id = acquisition
    return {"execution_id": execution_id, "step_id": step_id, **extra}


def _a_proposal(client: TestClient, plan_id: str) -> str:
    response = client.post("/proposals", json={"plan_id": plan_id, "parameters": {}})
    assert response.status_code == 201, response.text
    proposal_id: str = response.json()["proposal_id"]
    return proposal_id


def test_posting_a_proposal_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_proposal(client, _a_plan(client))


def test_an_open_proposal_reads_back_with_a_null_acquisition(client: TestClient) -> None:
    """The null IS the status, so the read has to carry both keys."""
    with client:
        plan_id = _a_plan(client)
        proposal_id = _a_proposal(client, plan_id)
        response = client.get(f"/proposals/{proposal_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal_id"] == proposal_id
    assert body["plan_id"] == plan_id
    assert (body["execution_id"], body["step_id"]) == (None, None)


def test_a_proposal_reads_back_with_a_proposer_nobody_sent(client: TestClient) -> None:
    with client:
        proposal_id = _a_proposal(client, _a_plan(client))
        response = client.get(f"/proposals/{proposal_id}")

    assert response.json()["actor_id"]


def test_omitting_the_parameters_is_accepted(client: TestClient) -> None:
    """A routine that takes no values should not need an empty object."""
    with client:
        response = client.post("/proposals", json={"plan_id": _a_plan(client)})

    assert response.status_code == 201, response.text


def test_taking_a_proposal_puts_the_acquisition_on_the_read(client: TestClient) -> None:
    with client:
        plan_id = _a_plan(client)
        execution_id, step_id = _an_acquisition_of(client, plan_id)
        proposal_id = _a_proposal(client, plan_id)

        taken = client.post(
            f"/proposals/{proposal_id}/take",
            json={"execution_id": execution_id, "step_id": step_id},
        )
        response = client.get(f"/proposals/{proposal_id}")

    assert taken.status_code == 204, taken.text
    body = response.json()
    assert (body["execution_id"], body["step_id"]) == (execution_id, step_id)


def test_taking_one_twice_is_409(client: TestClient) -> None:
    with client:
        plan_id = _a_plan(client)
        proposal_id = _a_proposal(client, plan_id)
        first = client.post(
            f"/proposals/{proposal_id}/take",
            json=_body(_an_acquisition_of(client, plan_id)),
        )
        second = client.post(
            f"/proposals/{proposal_id}/take",
            json=_body(_an_acquisition_of(client, plan_id)),
        )

    assert (first.status_code, second.status_code) == (204, 409)


def test_taking_with_an_acquisition_of_another_plan_is_409(client: TestClient) -> None:
    with client:
        proposal_id = _a_proposal(client, _a_plan(client))
        other = _an_acquisition_of(client, _a_plan(client))
        response = client.post(f"/proposals/{proposal_id}/take", json=_body(other))

    assert response.status_code == 409, response.text


def test_reading_a_proposal_that_was_never_made_is_404(client: TestClient) -> None:
    with client:
        response = client.get(f"/proposals/{uuid4()}")

    assert response.status_code == 404, response.text


def test_values_the_plans_schema_refuses_are_400(client: TestClient) -> None:
    """Counsel's own malformed-input class, registered by Counsel."""
    with client:
        plan_id = _a_plan(client, _TYPED_SCHEMA)
        response = client.post(
            "/proposals",
            json={"plan_id": plan_id, "parameters": {"exposure_time_s": "half a second"}},
        )

    assert response.status_code == 400, response.text


def test_naming_a_plan_that_does_not_exist_is_404(client: TestClient) -> None:
    """The sibling's error class, mapped by the sibling's registration."""
    with client:
        response = client.post("/proposals", json={"plan_id": str(uuid4()), "parameters": {}})

    assert response.status_code == 404, response.text


def test_taking_with_a_move_is_409_and_says_the_step_runs_no_plan(client: TestClient) -> None:
    """The refusal a run reference could not produce.

    A run was always a run. A step is a move or an acquisition, so this
    route can be handed a step that exists, belongs to a real execution,
    and still cannot have run what was proposed.
    """
    with client:
        proposal_id = _a_proposal(client, _a_plan(client))
        response = client.post(f"/proposals/{proposal_id}/take", json=_body(_a_move_in(client)))

    assert response.status_code == 409, response.text
    assert "runs no plan" in response.json()["detail"]


def test_taking_with_an_execution_that_does_not_exist_is_404(client: TestClient) -> None:
    """The sibling's error class again, on the other slice."""
    with client:
        proposal_id = _a_proposal(client, _a_plan(client))
        response = client.post(
            f"/proposals/{proposal_id}/take",
            json={"execution_id": str(uuid4()), "step_id": str(uuid4())},
        )

    assert response.status_code == 404, response.text


def test_a_naive_reported_time_on_a_take_is_400(client: TestClient) -> None:
    """The shared helper's error class, mapped by the context that first needed it."""
    with client:
        plan_id = _a_plan(client)
        proposal_id = _a_proposal(client, plan_id)
        response = client.post(
            f"/proposals/{proposal_id}/take",
            json=_body(_an_acquisition_of(client, plan_id), occurred_at="2026-09-18T06:00:00"),
        )

    assert response.status_code == 400, response.text


def test_replaying_an_idempotency_key_returns_the_first_proposal(client: TestClient) -> None:
    with client:
        plan_id = _a_plan(client)
        headers = {"Idempotency-Key": "agent-turn-41"}
        first = client.post("/proposals", json={"plan_id": plan_id}, headers=headers)
        second = client.post("/proposals", json={"plan_id": plan_id}, headers=headers)

    assert first.json()["proposal_id"] == second.json()["proposal_id"]
