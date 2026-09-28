"""Making, reading and taking a proposal over HTTP, through the real app.

The unit tests exercise the handlers directly, so neither they nor the
integration tier can see the two failures that live only on a route: a
request field bound to the wrong argument, and a domain error nobody
registered a status code for. Both leave every other tier green, and the
second is a 500.

That second one matters here, because this context registers four
handlers and relies on another context for four more. `OperationNotFoundError`,
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


def _an_operation(client: TestClient, schema: dict[str, Any] | None = None) -> str:
    response = client.post(
        "/operations",
        json={"name": "count", "parameters_schema": schema or _OPEN_SCHEMA},
    )
    assert response.status_code == 201, response.text
    operation_id: str = response.json()["operation_id"]
    return operation_id


def _an_acquisition_of(client: TestClient, operation_id: str) -> tuple[str, str]:
    """Compose a procedure that acquires with this operation and dispatch it.

    Three calls where a run took one, and all three are load bearing.
    There is no way to make a step without a procedure holding it and an
    execution dispatching that procedure, which is the whole content of
    the keeper owning the genesis.
    """
    defined = client.post(
        "/procedures",
        json={
            "name": "align_then_scan",
            "beamline": "2-bm",
            "steps": [
                {"kind": "set", "record": "2bmb:m1", "to": 0.0},
                {
                    "kind": "acquire",
                    "operation_id": operation_id,
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
    """A dispatched step that runs no operation."""
    defined = client.post(
        "/procedures",
        json={
            "name": "park",
            "beamline": "2-bm",
            "steps": [{"kind": "set", "record": "2bmb:m1", "to": 0.0}],
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


def _a_proposal(client: TestClient, operation_id: str) -> str:
    response = client.post("/proposals", json={"operation_id": operation_id, "parameters": {}})
    assert response.status_code == 201, response.text
    proposal_id: str = response.json()["proposal_id"]
    return proposal_id


def test_posting_a_proposal_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_proposal(client, _an_operation(client))


def test_an_open_proposal_reads_back_with_a_null_acquisition(client: TestClient) -> None:
    """The null IS the status, so the read has to carry both keys."""
    with client:
        operation_id = _an_operation(client)
        proposal_id = _a_proposal(client, operation_id)
        response = client.get(f"/proposals/{proposal_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal_id"] == proposal_id
    assert body["operation_id"] == operation_id
    assert (body["execution_id"], body["step_id"]) == (None, None)


def test_a_proposal_reads_back_with_a_proposer_nobody_sent(client: TestClient) -> None:
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        response = client.get(f"/proposals/{proposal_id}")

    assert response.json()["actor_id"]


def test_omitting_the_parameters_is_accepted(client: TestClient) -> None:
    """A routine that takes no values should not need an empty object."""
    with client:
        response = client.post("/proposals", json={"operation_id": _an_operation(client)})

    assert response.status_code == 201, response.text


def test_taking_a_proposal_puts_the_acquisition_on_the_read(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        execution_id, step_id = _an_acquisition_of(client, operation_id)
        proposal_id = _a_proposal(client, operation_id)

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
        operation_id = _an_operation(client)
        proposal_id = _a_proposal(client, operation_id)
        first = client.post(
            f"/proposals/{proposal_id}/take",
            json=_body(_an_acquisition_of(client, operation_id)),
        )
        second = client.post(
            f"/proposals/{proposal_id}/take",
            json=_body(_an_acquisition_of(client, operation_id)),
        )

    assert (first.status_code, second.status_code) == (204, 409)


def test_taking_with_an_acquisition_of_another_plan_is_409(client: TestClient) -> None:
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        other = _an_acquisition_of(client, _an_operation(client))
        response = client.post(f"/proposals/{proposal_id}/take", json=_body(other))

    assert response.status_code == 409, response.text


def test_reading_a_proposal_that_was_never_made_is_404(client: TestClient) -> None:
    with client:
        response = client.get(f"/proposals/{uuid4()}")

    assert response.status_code == 404, response.text


def test_values_the_plans_schema_refuses_are_400(client: TestClient) -> None:
    """Counsel's own malformed-input class, registered by Counsel."""
    with client:
        operation_id = _an_operation(client, _TYPED_SCHEMA)
        response = client.post(
            "/proposals",
            json={"operation_id": operation_id, "parameters": {"exposure_time_s": "half a second"}},
        )

    assert response.status_code == 400, response.text


def test_naming_a_plan_that_does_not_exist_is_404(client: TestClient) -> None:
    """The sibling's error class, mapped by the sibling's registration."""
    with client:
        response = client.post("/proposals", json={"operation_id": str(uuid4()), "parameters": {}})

    assert response.status_code == 404, response.text


def test_taking_with_a_move_is_409_and_says_the_step_runs_no_plan(client: TestClient) -> None:
    """The refusal a run reference could not produce.

    A run was always a run. A step is a move or an acquisition, so this
    route can be handed a step that exists, belongs to a real execution,
    and still cannot have run what was proposed.
    """
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        response = client.post(f"/proposals/{proposal_id}/take", json=_body(_a_move_in(client)))

    assert response.status_code == 409, response.text
    assert "runs no operation" in response.json()["detail"]


def test_taking_with_an_execution_that_does_not_exist_is_404(client: TestClient) -> None:
    """The sibling's error class again, on the other slice."""
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        response = client.post(
            f"/proposals/{proposal_id}/take",
            json={"execution_id": str(uuid4()), "step_id": str(uuid4())},
        )

    assert response.status_code == 404, response.text


def test_a_naive_reported_time_on_a_take_is_400(client: TestClient) -> None:
    """The shared helper's error class, mapped by the context that first needed it."""
    with client:
        operation_id = _an_operation(client)
        proposal_id = _a_proposal(client, operation_id)
        response = client.post(
            f"/proposals/{proposal_id}/take",
            json=_body(_an_acquisition_of(client, operation_id), occurred_at="2026-09-18T06:00:00"),
        )

    assert response.status_code == 400, response.text


def test_replaying_an_idempotency_key_returns_the_first_proposal(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        headers = {"Idempotency-Key": "agent-turn-41"}
        first = client.post("/proposals", json={"operation_id": operation_id}, headers=headers)
        second = client.post("/proposals", json={"operation_id": operation_id}, headers=headers)

    assert first.json()["proposal_id"] == second.json()["proposal_id"]


def _an_inquiry(client: TestClient, execution_id: str, objective: str = "find the edge") -> str:
    response = client.post(
        "/inquiries", json={"execution_id": execution_id, "objective": objective}
    )
    assert response.status_code == 201, response.text
    inquiry_id: str = response.json()["inquiry_id"]
    return inquiry_id


def test_posting_an_inquiry_returns_its_id(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        assert _an_inquiry(client, execution_id)


def test_an_unanswered_inquiry_reads_back_open_with_no_conclusion(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        read = client.get(f"/inquiries/{inquiry_id}")

    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "Open"
    assert body["conclusion"] is None
    assert body["observed_step_count"] is None
    assert body["execution_ended"] is None


def test_an_inquiry_reads_back_with_the_step_count_of_its_execution(client: TestClient) -> None:
    """Nothing in the request carries it, so a handler that stopped reading
    the execution is visible only here and on a read."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        read = client.get(f"/inquiries/{inquiry_id}")

    assert read.json()["execution_step_count"] == 2


def test_an_inquiry_reads_back_with_an_asker_nobody_sent(client: TestClient) -> None:
    """The asker is not a request field, so no test of the route model
    would catch it being dropped."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        read = client.get(f"/inquiries/{inquiry_id}")

    assert read.json()["actor_id"]


def test_claiming_an_inquiry_puts_it_in_the_middle_state(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        claimed = client.post(f"/inquiries/{inquiry_id}/claim")
        read = client.get(f"/inquiries/{inquiry_id}")

    assert claimed.status_code == 204, claimed.text
    assert read.json()["status"] == "Claimed"


def test_claiming_one_twice_is_409(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)
        assert client.post(f"/inquiries/{inquiry_id}/claim").status_code == 204

        again = client.post(f"/inquiries/{inquiry_id}/claim")

    assert again.status_code == 409, again.text


def test_answering_puts_the_conclusion_and_the_boundary_on_the_read(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        answered = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Stop", "observed_step_count": 1, "execution_ended": False},
        )
        read = client.get(f"/inquiries/{inquiry_id}")

    assert answered.status_code == 204, answered.text
    body = read.json()
    assert (body["status"], body["conclusion"]) == ("Answered", "Stop")
    assert (body["observed_step_count"], body["execution_ended"]) == (1, False)


def test_answering_without_claiming_first_is_accepted(client: TestClient) -> None:
    """Claiming is optional, and the route pair has to agree with the
    decider about that or a thinker handed its question cannot report."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        answered = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Abstain", "observed_step_count": 0, "execution_ended": False},
        )

    assert answered.status_code == 204, answered.text


def test_answering_one_twice_is_409(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)
        first = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Stop", "observed_step_count": 2, "execution_ended": True},
        )
        assert first.status_code == 204, first.text

        again = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Refer", "observed_step_count": 2, "execution_ended": True},
        )

    assert again.status_code == 409, again.text


def test_a_propose_answer_carries_the_proposal_onto_the_read(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        execution_id, _step_id = _an_acquisition_of(client, operation_id)
        inquiry_id = _an_inquiry(client, execution_id)
        proposal_id = _a_proposal(client, operation_id)

        answered = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={
                "conclusion": "Propose",
                "observed_step_count": 2,
                "execution_ended": True,
                "proposal_id": proposal_id,
            },
        )
        read = client.get(f"/inquiries/{inquiry_id}")

    assert answered.status_code == 204, answered.text
    assert read.json()["proposal_id"] == proposal_id


def test_a_propose_answer_naming_no_proposal_is_400(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        refused = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Propose", "observed_step_count": 2, "execution_ended": True},
        )

    assert refused.status_code == 400, refused.text


def test_a_stop_answer_naming_a_proposal_is_400(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        execution_id, _step_id = _an_acquisition_of(client, operation_id)
        inquiry_id = _an_inquiry(client, execution_id)
        proposal_id = _a_proposal(client, operation_id)

        refused = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={
                "conclusion": "Stop",
                "observed_step_count": 2,
                "execution_ended": True,
                "proposal_id": proposal_id,
            },
        )

    assert refused.status_code == 400, refused.text


def test_a_propose_answer_naming_a_proposal_nobody_made_is_404(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        refused = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={
                "conclusion": "Propose",
                "observed_step_count": 2,
                "execution_ended": True,
                "proposal_id": str(uuid4()),
            },
        )

    assert refused.status_code == 404, refused.text


def test_seeing_more_steps_than_the_execution_has_is_400(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        refused = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Stop", "observed_step_count": 99, "execution_ended": True},
        )

    assert refused.status_code == 400, refused.text


def test_a_fifth_conclusion_is_refused_at_the_wire(client: TestClient) -> None:
    """The closed type on the request model, which is what keeps a word
    this system has no meaning for from reaching a decider at all."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        refused = client.post(
            f"/inquiries/{inquiry_id}/answer",
            json={"conclusion": "Maybe", "observed_step_count": 1, "execution_ended": True},
        )

    assert refused.status_code == 422, refused.text


def test_an_empty_objective_is_refused_at_the_wire(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))

        refused = client.post("/inquiries", json={"execution_id": execution_id, "objective": ""})

    assert refused.status_code == 422, refused.text


def test_an_inquiry_about_an_execution_that_does_not_exist_is_404(client: TestClient) -> None:
    """Execution's error class reaching a Counsel route, which is the
    reliance no source file on either side can state."""
    with client:
        refused = client.post(
            "/inquiries", json={"execution_id": str(uuid4()), "objective": "find the edge"}
        )

    assert refused.status_code == 404, refused.text


def test_reading_an_inquiry_that_was_never_made_is_404(client: TestClient) -> None:
    with client:
        read = client.get(f"/inquiries/{uuid4()}")

    assert read.status_code == 404, read.text


def test_a_naive_reported_time_on_a_claim_is_400(client: TestClient) -> None:
    """The shared timestamp helper's error, mapped by Execution and relied
    on here."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        inquiry_id = _an_inquiry(client, execution_id)

        refused = client.post(
            f"/inquiries/{inquiry_id}/claim",
            json={"occurred_at": "2026-09-19T09:00:00"},
        )

    assert refused.status_code == 400, refused.text


def test_replaying_an_idempotency_key_returns_the_first_inquiry(client: TestClient) -> None:
    """The genesis mints an id, so a retry without a key would leave two
    records of one asking."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        body = {"execution_id": execution_id, "objective": "find the edge"}
        headers = {"Idempotency-Key": "one-question-asked-twice"}

        first = client.post("/inquiries", json=body, headers=headers)
        second = client.post("/inquiries", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.json()["inquiry_id"] == first.json()["inquiry_id"]


def test_finding_inquiries_narrows_to_the_claimed_ones(client: TestClient) -> None:
    """The staleness question, and the reason the filter is a status
    rather than a flag for answered."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        waiting = _an_inquiry(client, execution_id, objective="one")
        claimed = _an_inquiry(client, execution_id, objective="two")
        assert client.post(f"/inquiries/{claimed}/claim").status_code == 204

        page = client.get("/inquiries", params={"status": "Claimed"})

    assert page.status_code == 200, page.text
    found = [item["inquiry_id"] for item in page.json()["items"]]
    assert found == [claimed]
    assert waiting not in found


def test_finding_inquiries_with_no_filter_returns_every_state(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        waiting = _an_inquiry(client, execution_id, objective="one")
        answered = _an_inquiry(client, execution_id, objective="two")
        client.post(
            f"/inquiries/{answered}/answer",
            json={"conclusion": "Stop", "observed_step_count": 2, "execution_ended": True},
        )

        page = client.get("/inquiries")

    assert {item["inquiry_id"] for item in page.json()["items"]} == {waiting, answered}


def test_a_listed_inquiry_carries_the_question_itself(client: TestClient) -> None:
    """The objective rides on the row where a proposal's parameters do
    not, because a list of questions with the questions taken out is a
    list of identifiers."""
    with client:
        execution_id, _step_id = _an_acquisition_of(client, _an_operation(client))
        _an_inquiry(client, execution_id, objective="is one scan enough")

        page = client.get("/inquiries")

    assert page.json()["items"][0]["objective"] == "is one scan enough"


def _adopt(client: TestClient, proposal_id: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {"beamline": "2-bm", "scopes": ["2bmb:det:"]}
    body.update(overrides)
    return client.post(f"/proposals/{proposal_id}/adopt", json=body)


def test_adopting_a_proposal_returns_the_execution_it_dispatched(client: TestClient) -> None:
    """The one thing a caller cannot work out for itself, and the thing
    it will watch next."""
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))

        adopted = _adopt(client, proposal_id)

    assert adopted.status_code == 201, adopted.text
    assert adopted.json()["execution_id"]


def test_an_adopted_proposal_reads_back_pointing_at_its_acquisition(
    client: TestClient,
) -> None:
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        execution_id = _adopt(client, proposal_id).json()["execution_id"]

        proposal = client.get(f"/proposals/{proposal_id}").json()
        execution = client.get(f"/executions/{execution_id}").json()

    assert proposal["execution_id"] == execution_id
    assert proposal["step_id"] == execution["steps"][0]["step_id"]


def test_the_adopted_execution_is_waiting_for_a_driver(client: TestClient) -> None:
    """How an adopted proposal reaches a conductor: it becomes an
    ordinary dispatched execution, and the conductor knows nothing about
    proposals at all."""
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        execution_id = _adopt(client, proposal_id).json()["execution_id"]

        execution = client.get(f"/executions/{execution_id}").json()

    assert execution["status"] == "Dispatched"
    assert execution["beamline"] == "2-bm"


def test_adopting_the_same_proposal_twice_is_409(client: TestClient) -> None:
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        assert _adopt(client, proposal_id).status_code == 201

        again = _adopt(client, proposal_id)

    assert again.status_code == 409, again.text


def test_adopting_a_proposal_an_acquisition_already_took_is_409(client: TestClient) -> None:
    """Composing more work for advice something else already acted on
    would run it twice."""
    with client:
        operation_id = _an_operation(client)
        proposal_id = _a_proposal(client, operation_id)
        acquisition = _an_acquisition_of(client, operation_id)
        taken = client.post(f"/proposals/{proposal_id}/take", json=_body(acquisition))
        assert taken.status_code == 204, taken.text

        refused = _adopt(client, proposal_id)

    assert refused.status_code == 409, refused.text


def test_adopting_with_no_devices_is_refused_at_the_wire(client: TestClient) -> None:
    """A step believed to touch nothing can run beside another over the
    same motor, so an empty bound never reaches a decider."""
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))

        refused = _adopt(client, proposal_id, scopes=[])

    assert refused.status_code == 422, refused.text


def test_a_refused_adoption_leaves_the_proposal_open(client: TestClient) -> None:
    """Nothing is written until all three decisions are made, so a
    refusal anywhere in the slice leaves every stream as it was."""
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        refused = _adopt(client, proposal_id, beamline="")

        proposal = client.get(f"/proposals/{proposal_id}").json()
        open_ones = client.get("/proposals", params={"is_open": True}).json()

    assert refused.status_code in {400, 422}, refused.text
    assert proposal["execution_id"] is None
    assert proposal_id in {item["proposal_id"] for item in open_ones["items"]}


def test_adopting_a_proposal_that_was_never_made_is_404(client: TestClient) -> None:
    with client:
        refused = _adopt(client, str(uuid4()))

    assert refused.status_code == 404, refused.text


def test_a_listed_proposal_says_which_way_it_closed(client: TestClient) -> None:
    """The status the third state earned. A null test can say that
    something came of a proposal and not which of the two ways."""
    with client:
        operation_id = _an_operation(client)
        adopted_id = _a_proposal(client, operation_id)
        _adopt(client, adopted_id)
        taken_id = _a_proposal(client, operation_id)
        client.post(
            f"/proposals/{taken_id}/take", json=_body(_an_acquisition_of(client, operation_id))
        )
        open_id = _a_proposal(client, operation_id)

        listed = client.get("/proposals").json()["items"]

    by_id = {item["proposal_id"]: item["status"] for item in listed}
    assert by_id[adopted_id] == "Adopted"
    assert by_id[taken_id] == "Taken"
    assert by_id[open_id] == "Open"


def test_replaying_an_idempotency_key_returns_the_first_execution(client: TestClient) -> None:
    """A retry the domain would refuse has already dispatched something.
    The caller that could not tell whether its request landed needs the
    same execution back, not a 409 it has to go and interpret."""
    with client:
        proposal_id = _a_proposal(client, _an_operation(client))
        headers = {"Idempotency-Key": "one-adoption-sent-twice"}
        body = {"beamline": "2-bm", "scopes": ["2bmb:det:"]}

        first = client.post(f"/proposals/{proposal_id}/adopt", json=body, headers=headers)
        second = client.post(f"/proposals/{proposal_id}/adopt", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.json()["execution_id"] == first.json()["execution_id"]


def test_reading_one_proposal_says_which_way_it_closed(client: TestClient) -> None:
    """The single read carries the status, not only the listing.

    A live run found this missing after the listing had it: a caller
    holding one id could see that something came of its advice and not
    which of the two ways, which is the whole distinction the status
    was added to carry.
    """
    with client:
        operation_id = _an_operation(client)
        adopted_id = _a_proposal(client, operation_id)
        _adopt(client, adopted_id)
        open_id = _a_proposal(client, operation_id)

        adopted = client.get(f"/proposals/{adopted_id}").json()
        still_open = client.get(f"/proposals/{open_id}").json()

    assert adopted["status"] == "Adopted"
    assert still_open["status"] == "Open"
