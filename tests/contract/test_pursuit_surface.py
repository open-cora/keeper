"""Starting, reading and withdrawing a pursuit over HTTP, through the real app.

The unit tests exercise the handlers directly, so neither they nor the
integration tier can see the two failures that live only on a route: a
request field bound to the wrong argument, and a domain error nobody
registered a status code for. Both leave every other tier green, and the
second is a 500.

This context registers six error classes on four status codes and relies
on one more it does not register, `UnauthorizedError`, which every context
shares and `keeper.api.exception_handlers` maps once for all of them.
Whether that reliance holds is not something the source can state.

Four of the six sit on 400 and each guards a field a person is stating on
behalf of a machine. A pursuit is the one record here that grants a
standing permission, so a refusal that said only "bad request" would leave
the caller guessing which half of the permission was wrong. Every one of
them is walked below and each is checked to name its own field.

The authorizing actor is the other thing only this tier can see. It is not
a request field, so no unit test of the route model would catch it being
dropped: it comes off the authenticated principal, and what proves it is
reading the pursuit back and finding somebody named.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.infrastructure.settings import Settings
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_GOAL_MAX_LENGTH,
    PURSUIT_MAX_SCOPES,
)

pytestmark = pytest.mark.contract

_BODY: dict[str, Any] = {
    "goal": "find the edge of the useful exposure range",
    "beamline": "2-bm",
    "scopes": ["2bmb:m1", "2bmb:det"],
    "budget": {"Rounds": 8, "Tokens": 400000},
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def _a_pursuit(client: TestClient, **overrides: Any) -> str:
    response = client.post("/pursuits", json={**_BODY, **overrides})
    assert response.status_code == 201, response.text
    pursuit_id: str = response.json()["pursuit_id"]
    return pursuit_id


def test_starting_a_pursuit_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_pursuit(client)


def test_a_started_pursuit_reads_back_with_everything_it_was_authorized_over(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        body = client.get(f"/pursuits/{pursuit_id}").json()

        assert body["goal"] == _BODY["goal"]
        assert body["beamline"] == "2-bm"
        assert body["scopes"] == ["2bmb:m1", "2bmb:det"]
        assert body["budget"] == {"Rounds": 8, "Tokens": 400000}
        assert body["status"] == "Running"
        assert body["stopped_by"] is None


def test_the_authorizing_actor_is_on_the_record_without_being_a_request_field(
    client: TestClient,
) -> None:
    """Nothing in the body names who is authorizing, and the read has to
    name somebody. A standing permission whose author is unrecorded is not
    an authorization."""
    with client:
        pursuit_id = _a_pursuit(client)

        assert client.get(f"/pursuits/{pursuit_id}").json()["actor_id"]


def test_withdrawing_stops_the_pursuit_and_names_who_did_it(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        withdrawn = client.post(f"/pursuits/{pursuit_id}/withdraw")

        assert withdrawn.status_code == 204, withdrawn.text
        body = client.get(f"/pursuits/{pursuit_id}").json()
        assert (body["status"], body["stopped_by"] is not None) == ("Stopped", True)


def test_withdrawing_twice_is_a_conflict_rather_than_a_second_success(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        client.post(f"/pursuits/{pursuit_id}/withdraw")

        assert client.post(f"/pursuits/{pursuit_id}/withdraw").status_code == 409


def test_reading_a_pursuit_that_was_never_started_is_a_404(client: TestClient) -> None:
    with client:
        assert client.get(f"/pursuits/{uuid4()}").status_code == 404


def test_withdrawing_a_pursuit_that_was_never_started_is_a_404(client: TestClient) -> None:
    with client:
        assert client.post(f"/pursuits/{uuid4()}/withdraw").status_code == 404


def test_a_goal_of_only_whitespace_is_a_400_naming_the_goal(client: TestClient) -> None:
    """Past the model's own length bound, so this is the value object's
    refusal reaching the route rather than FastAPI's."""
    with client:
        response = client.post("/pursuits", json={**_BODY, "goal": "   "})

        assert response.status_code == 400, response.text
        assert "goal" in response.json()["detail"]


def test_a_beamline_of_only_whitespace_is_a_400_naming_the_beamline(
    client: TestClient,
) -> None:
    with client:
        response = client.post("/pursuits", json={**_BODY, "beamline": "   "})

        assert response.status_code == 400, response.text
        assert "beamline" in response.json()["detail"]


def test_a_scope_of_only_whitespace_is_a_400_naming_the_scopes(client: TestClient) -> None:
    """Refused rather than dropped, and the refusal says scopes, because a
    caller that sent a blank meant something by it."""
    with client:
        response = client.post("/pursuits", json={**_BODY, "scopes": ["2bmb:m1", "   "]})

        assert response.status_code == 400, response.text
        assert "scopes" in response.json()["detail"]


def test_a_budget_limit_that_is_not_positive_is_a_400_naming_the_budget(
    client: TestClient,
) -> None:
    with client:
        response = client.post("/pursuits", json={**_BODY, "budget": {"Rounds": 0}})

        assert response.status_code == 400, response.text
        assert "budget" in response.json()["detail"]


def test_a_budget_that_bounds_nothing_is_refused_before_a_pursuit_exists(
    client: TestClient,
) -> None:
    """The model refuses an empty mapping, so this is a 422 rather than the
    value object's 400. Both doors are shut and this is the outer one."""
    with client:
        assert client.post("/pursuits", json={**_BODY, "budget": {}}).status_code == 422


def test_no_scopes_at_all_is_refused_before_a_pursuit_exists(client: TestClient) -> None:
    with client:
        assert client.post("/pursuits", json={**_BODY, "scopes": []}).status_code == 422


def test_a_goal_longer_than_the_bound_is_refused_by_the_model(client: TestClient) -> None:
    with client:
        long_goal = "x" * (PURSUIT_GOAL_MAX_LENGTH + 1)

        assert client.post("/pursuits", json={**_BODY, "goal": long_goal}).status_code == 422


def test_more_scopes_than_the_bound_is_refused_by_the_model(client: TestClient) -> None:
    with client:
        many = [f"scope-{index}" for index in range(PURSUIT_MAX_SCOPES + 1)]

        assert client.post("/pursuits", json={**_BODY, "scopes": many}).status_code == 422


def test_a_dimension_the_enum_does_not_know_is_refused_by_the_model(
    client: TestClient,
) -> None:
    """The budget's keys are a closed set on the wire as well as in the
    fold, so a deployment cannot invent a dimension nothing will ever
    count against."""
    with client:
        response = client.post("/pursuits", json={**_BODY, "budget": {"Neutrons": 4}})

        assert response.status_code == 422, response.text


def test_replaying_an_idempotency_key_returns_the_same_pursuit(client: TestClient) -> None:
    """The one duplicate this context can least afford. A retry with no key
    would leave a second standing authorization nobody asked for, running
    its own budget against the same beamline."""
    with client:
        headers = {"Idempotency-Key": "a-retried-start"}

        first = client.post("/pursuits", json=_BODY, headers=headers)
        second = client.post("/pursuits", json=_BODY, headers=headers)

        assert first.status_code == 201, first.text
        assert second.json()["pursuit_id"] == first.json()["pursuit_id"]


def test_replaying_a_withdrawal_with_its_key_is_told_it_worked(
    client: TestClient,
) -> None:
    """The only transition in this tree that answers a retry from cache.

    A handler returning None could not be wrapped until the store learned
    to record a completed row without a stored result, and this is the
    slice that drove the change. What a caller with a timed-out request
    sees now is the answer it missed rather than a refusal.
    """
    with client:
        pursuit_id = _a_pursuit(client)
        headers = {"Idempotency-Key": "a-retried-withdrawal"}

        first = client.post(f"/pursuits/{pursuit_id}/withdraw", headers=headers)
        second = client.post(f"/pursuits/{pursuit_id}/withdraw", headers=headers)

        assert (first.status_code, second.status_code) == (204, 204), second.text


def test_withdrawing_again_under_a_different_key_still_meets_the_decider(
    client: TestClient,
) -> None:
    """The key replays one caller's own retry and nothing else.

    Sibling of the check above, and the pair is the point: a cache that
    answered every repeat would hide a second person stopping a pursuit
    that had already stopped, which is a real thing to be told about.
    """
    with client:
        pursuit_id = _a_pursuit(client)

        first = client.post(f"/pursuits/{pursuit_id}/withdraw", headers={"Idempotency-Key": "one"})
        second = client.post(
            f"/pursuits/{pursuit_id}/withdraw", headers={"Idempotency-Key": "another"}
        )

        assert (first.status_code, second.status_code) == (204, 409), second.text


def _an_execution(client: TestClient) -> str:
    """Dispatch something real for a round to observe."""
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
    return execution_id


def test_opening_a_round_returns_the_inquiry_a_thinker_should_answer(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        execution_id = _an_execution(client)

        opened = client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": execution_id})

        assert opened.status_code == 201, opened.text
        assert opened.json()["inquiry_id"]


def test_the_inquiry_a_round_opens_carries_the_pursuits_goal(client: TestClient) -> None:
    """Only this tier can see it. The objective is not a request field on
    the round, so a route that dropped it would leave every other tier
    green."""
    with client:
        pursuit_id = _a_pursuit(client)
        execution_id = _an_execution(client)

        opened = client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": execution_id})
        inquiry = client.get(f"/inquiries/{opened.json()['inquiry_id']}").json()

        assert inquiry["objective"] == _BODY["goal"]
        assert inquiry["execution_id"] == execution_id


def test_a_second_round_about_one_execution_is_a_conflict(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        execution_id = _an_execution(client)
        client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": execution_id})

        again = client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": execution_id})

        assert again.status_code == 409, again.text


def test_a_round_on_a_withdrawn_pursuit_is_a_conflict(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        execution_id = _an_execution(client)
        client.post(f"/pursuits/{pursuit_id}/withdraw")

        opened = client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": execution_id})

        assert opened.status_code == 409, opened.text


def test_a_round_past_the_budget_is_a_conflict_naming_the_dimension(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client, budget={"Rounds": 1})
        client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": _an_execution(client)})

        past = client.post(
            f"/pursuits/{pursuit_id}/rounds", json={"execution_id": _an_execution(client)}
        )

        assert past.status_code == 409, past.text
        assert "Rounds" in past.json()["detail"]


def test_a_round_naming_an_execution_that_does_not_exist_is_a_404(client: TestClient) -> None:
    """`ExecutionNotFoundError` is Execution's and reaches a Pursuit route.
    Nothing in this context registers it, and only this tier can say
    whether the reliance holds."""
    with client:
        pursuit_id = _a_pursuit(client)

        opened = client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": str(uuid4())})

        assert opened.status_code == 404, opened.text


def test_charging_answers_with_where_the_budget_now_stands(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        first = client.post(
            f"/pursuits/{pursuit_id}/charges", json={"dimension": "Tokens", "amount": 12500}
        )
        second = client.post(
            f"/pursuits/{pursuit_id}/charges", json={"dimension": "Tokens", "amount": 500}
        )

        assert first.status_code == 201, first.text
        assert (first.json()["total"], second.json()["total"]) == (12500, 13000)


def test_charging_a_dimension_this_system_counts_for_itself_is_a_400(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        charged = client.post(
            f"/pursuits/{pursuit_id}/charges", json={"dimension": "Rounds", "amount": 3}
        )

        assert charged.status_code == 400, charged.text
        assert "Rounds" in charged.json()["detail"]


def test_charging_a_dimension_the_pursuit_was_not_bounded_in_is_a_400(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        charged = client.post(
            f"/pursuits/{pursuit_id}/charges", json={"dimension": "BeamSeconds", "amount": 90}
        )

        assert charged.status_code == 400, charged.text


def test_an_amount_that_is_not_positive_is_refused_by_the_model(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        charged = client.post(
            f"/pursuits/{pursuit_id}/charges", json={"dimension": "Tokens", "amount": 0}
        )

        assert charged.status_code == 422, charged.text


def test_a_charge_carrying_a_naive_timestamp_is_a_400(client: TestClient) -> None:
    """`InvalidOccurredAtError` is the shared helper's, registered by
    Execution for the whole application. This context relies on it and
    cannot say so in its own source."""
    with client:
        pursuit_id = _a_pursuit(client)

        charged = client.post(
            f"/pursuits/{pursuit_id}/charges",
            json={"dimension": "Tokens", "amount": 10, "occurred_at": "2026-09-27T09:00:00"},
        )

        assert charged.status_code == 400, charged.text


def test_charging_a_pursuit_that_was_never_started_is_a_404(client: TestClient) -> None:
    with client:
        charged = client.post(
            f"/pursuits/{uuid4()}/charges", json={"dimension": "Tokens", "amount": 10}
        )

        assert charged.status_code == 404, charged.text


def test_replaying_a_charge_key_adds_it_once_rather_than_twice(client: TestClient) -> None:
    """The one retry key in this context that does something. Charges add
    rather than replace, so a redelivered one is beam time spent twice on a
    record that cannot be edited."""
    with client:
        pursuit_id = _a_pursuit(client)
        headers = {"Idempotency-Key": "a-retried-charge"}
        body = {"dimension": "Tokens", "amount": 250}

        first = client.post(f"/pursuits/{pursuit_id}/charges", json=body, headers=headers)
        second = client.post(f"/pursuits/{pursuit_id}/charges", json=body, headers=headers)

        assert (first.json()["total"], second.json()["total"]) == (250, 250)


def _an_answered_round(client: TestClient, pursuit_id: str, **answer: Any) -> int:
    """Open a round and put an answer on its inquiry, ready to be closed."""
    opened = client.post(
        f"/pursuits/{pursuit_id}/rounds", json={"execution_id": _an_execution(client)}
    )
    assert opened.status_code == 201, opened.text
    body = {"conclusion": "Abstain", "observed_step_count": 0, "execution_ended": True}
    body.update(answer)
    answered = client.post(f"/inquiries/{opened.json()['inquiry_id']}/answer", json=body)
    assert answered.status_code == 204, answered.text
    return len(client.get(f"/pursuits/{pursuit_id}").json().get("rounds", [])) or 0


def _a_proposal(client: TestClient) -> str:
    operation = client.post(
        "/operations",
        json={
            "name": "count",
            "parameters_schema": {"$schema": "https://json-schema.org/draft/2020-12/schema"},
        },
    )
    assert operation.status_code == 201, operation.text
    proposed = client.post(
        "/proposals", json={"operation_id": operation.json()["operation_id"], "parameters": {}}
    )
    assert proposed.status_code == 201, proposed.text
    proposal_id: str = proposed.json()["proposal_id"]
    return proposal_id


def test_closing_on_a_proposal_dispatches_a_run_at_the_pursuits_beamline(
    client: TestClient,
) -> None:
    """Only this tier can see it. Nothing in the closing request names a
    beamline, so a route that lost the pursuit's would leave every other
    tier green and dispatch work somewhere nobody authorized."""
    with client:
        pursuit_id = _a_pursuit(client, beamline="7-bm")
        _an_answered_round(
            client, pursuit_id, conclusion="Propose", proposal_id=_a_proposal(client)
        )

        closed = client.post(f"/pursuits/{pursuit_id}/rounds/0/close")

        assert closed.status_code == 200, closed.text
        assert closed.json()["outcome"] == "Advanced"
        dispatched = closed.json()["dispatched_id"]
        assert client.get(f"/executions/{dispatched}").json()["beamline"] == "7-bm"


def test_closing_on_a_stop_ends_the_pursuit(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        _an_answered_round(client, pursuit_id, conclusion="Stop")

        closed = client.post(f"/pursuits/{pursuit_id}/rounds/0/close")

        assert closed.json() == {
            "pursuit_id": pursuit_id,
            "round_index": 0,
            "outcome": "Completed",
            "dispatched_id": None,
        }
        assert client.get(f"/pursuits/{pursuit_id}").json()["status"] == "Stopped"


def test_closing_on_an_abstention_holds_the_pursuit_and_it_can_be_resumed(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        _an_answered_round(client, pursuit_id, conclusion="Abstain")

        closed = client.post(f"/pursuits/{pursuit_id}/rounds/0/close")
        held = client.get(f"/pursuits/{pursuit_id}").json()["status"]
        resumed = client.post(f"/pursuits/{pursuit_id}/resume")

        assert (closed.json()["outcome"], held) == ("Stalled", "Held")
        assert resumed.status_code == 204, resumed.text
        assert client.get(f"/pursuits/{pursuit_id}").json()["status"] == "Running"


def test_closing_a_round_whose_inquiry_has_no_answer_is_a_conflict(
    client: TestClient,
) -> None:
    with client:
        pursuit_id = _a_pursuit(client)
        client.post(f"/pursuits/{pursuit_id}/rounds", json={"execution_id": _an_execution(client)})

        closed = client.post(f"/pursuits/{pursuit_id}/rounds/0/close")

        assert closed.status_code == 409, closed.text


def test_closing_a_round_that_does_not_exist_is_a_conflict(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        assert client.post(f"/pursuits/{pursuit_id}/rounds/7/close").status_code == 409


def test_resuming_a_running_pursuit_is_a_conflict(client: TestClient) -> None:
    with client:
        pursuit_id = _a_pursuit(client)

        assert client.post(f"/pursuits/{pursuit_id}/resume").status_code == 409


def test_resuming_a_pursuit_that_was_never_started_is_a_404(client: TestClient) -> None:
    with client:
        assert client.post(f"/pursuits/{uuid4()}/resume").status_code == 404
