"""Writing and reading a plan over HTTP, through the app the process builds.

The unit tests exercise the handlers directly and the integration tests
exercise them against real SQL. Neither goes through a route, so neither
can see the two failures that live only there: a request field bound to
the wrong argument, and a domain error nobody registered a status code
for. Both leave every other tier green, and the second is a 500.

The name is checked twice on this path and the two checks answer to
different callers, so both are walked here. A name Pydantic can refuse
never reaches a command; one it cannot is refused by the value object
inside the decider. They produce different statuses, which is the only
way to tell from outside which one fired.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.execution.aggregates.plan import PLAN_NAME_MAX_LENGTH
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def _a_plan(client: TestClient, name: str = "count") -> str:
    response = client.post("/plans", json={"name": name, "parameters_schema": _SCHEMA})
    assert response.status_code == 201, response.text
    plan_id: str = response.json()["plan_id"]
    return plan_id


def test_posting_a_plan_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_plan(client)


def test_a_defined_plan_reads_back_with_its_name_and_schema(client: TestClient) -> None:
    with client:
        plan_id = _a_plan(client)
        response = client.get(f"/plans/{plan_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "plan_id": plan_id,
        "name": "count",
        "parameters_schema": _SCHEMA,
    }


def test_the_schema_reads_back_byte_for_byte(client: TestClient) -> None:
    """Not re-rendered on the way out, and this is what says so.

    A caller validating a request locally has to be validating against
    the same document this system will validate against. A route that
    rebuilt the schema from a parsed form, or dropped a keyword it did
    not recognise, would hand out a contract nothing enforces, and an
    equality on the whole dict is what notices.
    """
    ordered = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["exposure_seconds"],
        "properties": {"exposure_seconds": {"minimum": 0, "type": "number"}},
    }
    with client:
        created = client.post("/plans", json={"name": "count", "parameters_schema": ordered})
        plan_id = created.json()["plan_id"]
        response = client.get(f"/plans/{plan_id}")

    assert response.json()["parameters_schema"] == ordered


def test_reading_a_plan_that_was_never_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get("/plans/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_a_schema_outside_the_stored_subset_is_a_bad_request(client: TestClient) -> None:
    """The domain refusal, reached through the stack and mapped to a status.

    A decider raising the right error and a routes module that never
    learned about it both look correct in isolation, and together they
    are a 500.
    """
    with client:
        response = client.post(
            "/plans",
            json={"name": "count", "parameters_schema": {"type": "object"}},
        )
    assert response.status_code == 400, response.text


def test_a_whitespace_only_name_is_a_bad_request(client: TestClient) -> None:
    """Three spaces pass the length bound and are still not a name.

    Pydantic counts characters, so this body is well-formed as far as the
    edge can tell. The value object trims first and then counts, which is
    the check that catches it, and 400 rather than 422 is what says which
    of the two fired.
    """
    with client:
        response = client.post("/plans", json={"name": "   ", "parameters_schema": _SCHEMA})
    assert response.status_code == 400, response.text


def test_an_over_long_name_is_unprocessable(client: TestClient) -> None:
    """Refused at the edge, before a command is built.

    The other half of the pair above. This one never reaches the decider,
    so the status is FastAPI's own rather than one this context mapped.
    """
    with client:
        response = client.post(
            "/plans",
            json={"name": "x" * (PLAN_NAME_MAX_LENGTH + 1), "parameters_schema": _SCHEMA},
        )
    assert response.status_code == 422


def test_a_body_with_no_schema_is_unprocessable(client: TestClient) -> None:
    """Required, with no default, so omitting it is a malformed request.

    A plan whose parameters nobody described is the state the aggregate
    exists to refuse, and reaching it by leaving a key out would make the
    refusal look like a bug in the client.
    """
    with client:
        response = client.post("/plans", json={"name": "count"})
    assert response.status_code == 422


def _a_procedure(client: TestClient, name: str = "align_then_scan", beamline: str = "2-bm") -> str:
    """A plan and a procedure that moves once and acquires once."""
    plan_id = _a_plan(client, name="tomo_scan")
    response = client.post(
        "/procedures",
        json={
            "name": name,
            "beamline": beamline,
            "steps": [
                {"kind": "move", "record": "2bmb:m1", "to": 0.0},
                {
                    "kind": "acquire",
                    "plan_id": plan_id,
                    "parameters": {"exposure_seconds": 0.1},
                    "scopes": ["2bmb:det:"],
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    procedure_id: str = response.json()["procedure_id"]
    return procedure_id


def _a_dispatch(client: TestClient, procedure_id: str) -> str:
    response = client.post("/executions", json={"procedure_id": procedure_id})
    assert response.status_code == 201, response.text
    execution_id: str = response.json()["execution_id"]
    return execution_id


def test_a_dispatched_execution_reads_back_with_its_procedure_and_steps(
    client: TestClient,
) -> None:
    with client:
        procedure_id = _a_procedure(client)
        execution_id = _a_dispatch(client, procedure_id)
        response = client.get(f"/executions/{execution_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["procedure_id"] == procedure_id
    assert body["procedure_name"] == "align_then_scan"
    assert body["status"] == "Dispatched"
    assert body["steps"][0]["describes"] == "move 2bmb:m1 to 0.0"


def test_the_execution_response_carries_exactly_the_fields_an_execution_has(
    client: TestClient,
) -> None:
    """The shape, pinned, so a field arrives deliberately rather than drifting."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        body = client.get(f"/executions/{execution_id}").json()

    assert set(body) == {
        "execution_id",
        "procedure_id",
        "procedure_name",
        "beamline",
        "status",
        "steps",
    }
    assert set(body["steps"][0]) == {
        "step_id",
        "describes",
        "procedure_step_id",
        "outcome",
        "engine_reference",
        "engine_state",
        "cause",
    }


def test_dispatching_a_procedure_that_does_not_exist_is_not_found(client: TestClient) -> None:
    """The handler's refusal, reached through the stack and given a status."""
    with client:
        response = client.post("/executions", json={"procedure_id": str(uuid4())})

    assert response.status_code == 404, response.text


def test_reading_an_execution_that_was_never_dispatched_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get(f"/executions/{uuid4()}")

    assert response.status_code == 404, response.text


def test_a_claim_moves_a_dispatched_execution_and_a_second_one_is_a_conflict(
    client: TestClient,
) -> None:
    """The transient this context added, walked through the stack.

    Two drivers believing they own one traversal is what the Dispatched
    status exists to make visible, and the second claim being refused is
    the only place that shows.
    """
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        first = client.post(f"/executions/{execution_id}/claim")
        claimed = client.get(f"/executions/{execution_id}").json()["status"]
        second = client.post(f"/executions/{execution_id}/claim")

    assert (first.status_code, claimed, second.status_code) == (204, "Claimed", 409)


@pytest.mark.parametrize(
    ("outcome", "body"),
    [
        ("Done", {"outcome": "Done", "engine_reference": "uid-one"}),
        ("Refused", {"outcome": "Refused"}),
        ("Broken", {"outcome": "Broken", "cause": "MotorTimeout"}),
        ("Skipped", {"outcome": "Skipped"}),
    ],
)
def test_each_outcome_lands_on_the_step_it_names(
    client: TestClient, outcome: str, body: dict[str, Any]
) -> None:
    """Four outcomes, four shapes, one route.

    Parametrized because each outcome admits a different detail and the
    route binds all of them from one model, so a field bound to the wrong
    argument would show on one row and not the others.
    """
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        reported = client.post(f"/executions/{execution_id}/steps", json={**body, "index": 0})
        step = client.get(f"/executions/{execution_id}").json()["steps"][0]

    assert reported.status_code == 204, reported.text
    assert step["outcome"] == outcome


def test_reporting_one_step_twice_is_a_conflict(client: TestClient) -> None:
    """A step ends exactly once, and a second reading is either a repeated
    send or two drivers reporting one execution."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        client.post(f"/executions/{execution_id}/steps", json={"index": 0, "outcome": "Done"})
        again = client.post(
            f"/executions/{execution_id}/steps", json={"index": 0, "outcome": "Done"}
        )

    assert again.status_code == 409, again.text


def test_reporting_a_step_past_the_end_of_the_list_is_not_found(client: TestClient) -> None:
    """The step list is fixed at the genesis, so this means the caller and
    the record disagree about what is being walked."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/steps", json={"index": 7, "outcome": "Done"}
        )

    assert response.status_code == 404, response.text


def test_a_detail_belonging_to_another_outcome_is_a_bad_request(client: TestClient) -> None:
    """Each outcome has exactly one shape, and dropping the extra quietly
    would lose whichever of the two was right."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/steps",
            json={"index": 0, "outcome": "Done", "cause": "MotorTimeout"},
        )

    assert response.status_code == 400, response.text


def test_ending_an_execution_twice_is_a_conflict(client: TestClient) -> None:
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        first = client.post(f"/executions/{execution_id}/end")
        second = client.post(f"/executions/{execution_id}/end")

    assert (first.status_code, second.status_code) == (204, 409)


def test_something_arriving_after_an_execution_ended_is_a_conflict(client: TestClient) -> None:
    """An execution that has ended takes nothing further: the record is what
    it was when it closed, and a late step would rewrite history a reader
    may already have acted on."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        client.post(f"/executions/{execution_id}/end")
        late = client.post(
            f"/executions/{execution_id}/steps", json={"index": 0, "outcome": "Done"}
        )

    assert late.status_code == 409, late.text


@pytest.mark.parametrize("verb", ["claim", "end"])
def test_a_transition_accepts_a_reported_timestamp_in_its_body(
    client: TestClient, verb: str
) -> None:
    """The body model is written once per slice, so a slice whose route
    declared the field without passing it to the command would fail
    nowhere else."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/{verb}",
            json={"occurred_at": "2019-03-04T09:30:00Z"},
        )

    assert response.status_code == 204, response.text


@pytest.mark.parametrize("verb", ["claim", "end"])
def test_a_transition_still_accepts_no_body_at_all(client: TestClient, verb: str) -> None:
    """The body stays optional. A caller that sends none gets the moment the
    report arrived."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(f"/executions/{execution_id}/{verb}")

    assert response.status_code == 204, response.text


def test_a_timestamp_without_a_timezone_is_a_bad_request(client: TestClient) -> None:
    """The value object's refusal, reached through the stack and given a status.

    A naive datetime parses fine as far as Pydantic is concerned, so this
    is not a 422 from the edge. It is refused inside the command, and
    `InvalidOccurredAtError` had to be registered for 400 or this would
    be a 500.
    """
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/claim",
            json={"occurred_at": "2019-03-04T09:30:00"},
        )

    assert response.status_code == 400, response.text


def test_replaying_an_idempotency_key_returns_the_first_execution(client: TestClient) -> None:
    """A retry gets the execution it already dispatched, not a second one.

    Dispatching the same procedure again on purpose is an ordinary thing
    to do, so the key is what separates that from a retried request.
    """
    headers = {"Idempotency-Key": "a-retried-dispatch"}
    with client:
        body = {"procedure_id": _a_procedure(client)}
        first = client.post("/executions", json=body, headers=headers)
        second = client.post("/executions", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["execution_id"] == second.json()["execution_id"]


def test_listing_executions_finds_the_ones_dispatched_for_a_procedure(
    client: TestClient,
) -> None:
    """A routine composed once is executed every time it runs, so many rows
    under one procedure is the ordinary case rather than a duplicate."""
    with client:
        procedure_id = _a_procedure(client)
        _a_dispatch(client, procedure_id)
        _a_dispatch(client, procedure_id)
        _a_dispatch(client, _a_procedure(client, name="something_else"))
        response = client.get("/executions", params={"procedure_id": procedure_id})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2
    assert {item["procedure_id"] for item in items} == {procedure_id}


def test_the_work_intake_query_returns_only_what_this_beamline_has_not_taken_up(
    client: TestClient,
) -> None:
    """The request a conductor makes, through the stack rather than the port.

    Four executions: one at 7-BM, one at 2-BM already claimed, and two at
    2-BM still waiting. Only the two are work for a conductor at 2-BM,
    and either filter alone would hand it something it must not drive.
    """
    with client:
        here = _a_procedure(client, name="align_here", beamline="2-bm")
        elsewhere = _a_procedure(client, name="align_there", beamline="7-bm")
        waiting = [_a_dispatch(client, here), _a_dispatch(client, here)]
        _a_dispatch(client, elsewhere)
        claimed = _a_dispatch(client, here)
        assert client.post(f"/executions/{claimed}/claim").status_code == 204

        response = client.get("/executions", params={"beamline": "2-bm", "status": "Dispatched"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["execution_id"] for item in items} == set(waiting)
    assert all(item["beamline"] == "2-bm" for item in items)


def test_an_idle_beamline_asking_for_work_gets_an_empty_page_not_a_refusal(
    client: TestClient,
) -> None:
    """What a conductor gets most of the time it asks."""
    with client:
        _a_dispatch(client, _a_procedure(client, beamline="2-bm"))
        response = client.get("/executions", params={"beamline": "32-id", "status": "Dispatched"})

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_a_wait_returns_at_once_when_there_is_already_work(client: TestClient) -> None:
    """The long poll only holds a request that would answer empty."""
    with client:
        dispatched = _a_dispatch(client, _a_procedure(client, beamline="2-bm"))
        response = client.get(
            "/executions",
            params={"beamline": "2-bm", "status": "Dispatched", "wait": 30},
        )

    assert response.status_code == 200, response.text
    assert [item["execution_id"] for item in response.json()["items"]] == [dispatched]


def test_a_wait_past_the_ceiling_is_refused_rather_than_silently_shortened(
    client: TestClient,
) -> None:
    """A caller that asked to hold a connection for an hour gets told no.

    Bounded at the boundary rather than clamped, because a clamp would
    have the caller believe it is waiting far longer than it is and
    treat every return as a real answer.
    """
    with client:
        response = client.get("/executions", params={"wait": 3600})

    assert response.status_code == 422, response.text


def test_asking_for_a_status_that_is_not_one_is_refused_at_the_boundary(
    client: TestClient,
) -> None:
    """The status is an enum on the query string, so a typo is a 422 from
    the boundary rather than a silent empty page that reads like no work."""
    with client:
        response = client.get("/executions", params={"status": "Dispatchd"})

    assert response.status_code == 422, response.text


def test_listing_executions_that_match_nothing_is_an_empty_page_not_a_refusal(
    client: TestClient,
) -> None:
    """An absence is an answer, not an error."""
    with client:
        response = client.get("/executions", params={"procedure_id": str(uuid4())})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_listing_executions_with_a_cursor_that_did_not_come_from_a_response_is_refused(
    client: TestClient,
) -> None:
    """A cursor is opaque, and a caller that made one up is depending on an
    encoding this is free to change.

    422 rather than 400, because the refusal is registered at the
    composition root: `InvalidCursorError` belongs to infrastructure and
    every list endpoint in the tree answers with the same status.
    """
    with client:
        response = client.get("/executions", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422, response.text


def test_asking_for_more_executions_than_a_page_holds_is_refused_by_the_surface(
    client: TestClient,
) -> None:
    """The bound is on the request model, so this is the edge refusing
    rather than the domain."""
    with client:
        response = client.get("/executions", params={"limit": 5000})

    assert response.status_code == 422, response.text


def test_replaying_an_idempotency_key_returns_the_first_plan(client: TestClient) -> None:
    """A retry gets the plan it already made, not a second one."""
    body = {"name": "count", "parameters_schema": _SCHEMA}
    headers = {"Idempotency-Key": "a-retried-request"}
    with client:
        first = client.post("/plans", json=body, headers=headers)
        second = client.post("/plans", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["plan_id"] == second.json()["plan_id"]


def test_listing_plans_finds_every_plan_written_down_under_a_name(
    client: TestClient,
) -> None:
    """A name may match more than one plan on purpose, so the endpoint
    returns however many there are. An adapter resolving a routine's name
    to a plan has to see both and decide, which it cannot do if this
    picks one."""
    with client:
        first = _a_plan(client)
        second = _a_plan(client)
        _a_plan(client, name="scan")
        response = client.get("/plans", params={"name": "count"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["plan_id"] for item in body["items"]] == [second, first]
    assert body["next_cursor"] is None


def test_a_plan_summary_carries_exactly_the_fields_a_list_row_has(
    client: TestClient,
) -> None:
    """The shape, pinned. No schema, because a page of fifty would be a
    page of schemas, and one timestamp because a plan has one event."""
    with client:
        _a_plan(client)
        body = client.get("/plans").json()

    (row,) = body["items"]
    assert set(body) == {"items", "next_cursor"}
    assert set(row) == {"plan_id", "name", "created_at"}
    assert row["name"] == "count"


def test_listing_plans_by_a_name_nothing_uses_is_an_empty_page(client: TestClient) -> None:
    with client:
        _a_plan(client)
        response = client.get("/plans", params={"name": "absent"})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_listing_plans_by_a_name_over_the_bound_is_refused(client: TestClient) -> None:
    """The filter goes through the same value object the defining command
    does, so a name no plan could carry is refused rather than quietly
    matching nothing."""
    with client:
        response = client.get("/plans", params={"name": "x" * 500})

    assert response.status_code == 400, response.text


def test_a_page_of_plans_hands_back_a_cursor_that_reaches_the_rest(
    client: TestClient,
) -> None:
    with client:
        defined = [_a_plan(client, name=f"p{i}") for i in range(3)]
        first = client.get("/plans", params={"limit": 2}).json()
        second = client.get("/plans", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    walked = [item["plan_id"] for page in (first, second) for item in page["items"]]
    assert walked == list(reversed(defined))
    assert second["next_cursor"] is None


def _an_acquisition(client: TestClient) -> tuple[str, str]:
    """A dispatched execution and the id of its one acquisition step."""
    plan_id = _a_plan(client, name="tomo_scan")
    defined = client.post(
        "/procedures",
        json={
            "name": "one_scan",
            "beamline": "2-bm",
            "steps": [
                {
                    "kind": "acquire",
                    "plan_id": plan_id,
                    "parameters": {"exposure_seconds": 0.1},
                    "scopes": ["2bmb:det:"],
                }
            ],
        },
    )
    assert defined.status_code == 201, defined.text
    dispatched = client.post("/executions", json={"procedure_id": defined.json()["procedure_id"]})
    assert dispatched.status_code == 201, dispatched.text
    execution_id: str = dispatched.json()["execution_id"]
    read = client.get(f"/executions/{execution_id}")
    step_id: str = read.json()["steps"][0]["step_id"]
    return execution_id, step_id


def test_an_engine_report_is_accepted_and_shows_on_the_step(client: TestClient) -> None:
    """The route a reporter posts every document to.

    Walked here because the engine state is the one field on a step that
    no other surface writes, so a body field bound to the wrong argument
    would leave every other tier green.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        reported = client.post(
            f"/executions/{execution_id}/steps/{step_id}/run",
            json={"reported": "Started", "engine_reference": "uid-cycling"},
        )
        read = client.get(f"/executions/{execution_id}")

    assert reported.status_code == 204, reported.text
    step = read.json()["steps"][0]
    assert (step["engine_state"], step["engine_reference"]) == ("Running", "uid-cycling")


def test_a_report_that_does_not_follow_the_last_one_is_409(client: TestClient) -> None:
    """A redelivery is the case this status is chosen for.

    A reporter draining a document stream sends the same stop twice after
    any restart, and the second one is the system working. As a 400 it
    read as a malformed request, which is the one refusal a reporter must
    be able to tell apart from a bug in itself.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        path = f"/executions/{execution_id}/steps/{step_id}/run"
        client.post(path, json={"reported": "Started"})
        client.post(path, json={"reported": "Completed"})
        again = client.post(path, json={"reported": "Completed"})

    assert again.status_code == 409, again.text
    assert "does not follow" in again.json()["detail"]


def test_an_engine_report_for_a_step_nobody_dispatched_is_404(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition(client)
        response = client.post(
            f"/executions/{execution_id}/steps/{uuid4()}/run",
            json={"reported": "Started"},
        )

    assert response.status_code == 404, response.text
