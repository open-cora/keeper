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


def test_replaying_a_withdrawal_is_refused_like_every_other_transition(
    client: TestClient,
) -> None:
    """The wrapper was wired here first and backed out, so this pins the
    behaviour that replaced it.

    `with_idempotency` cannot carry a handler that returns None: a stored
    result of None reads as no stored result, so the replay runs the
    handler again and caches the refusal. `wire.py` holds the whole
    argument. What a caller sees is a 409, which is what a replayed
    transition is everywhere else in this tree.
    """
    with client:
        pursuit_id = _a_pursuit(client)
        headers = {"Idempotency-Key": "a-retried-withdrawal"}

        first = client.post(f"/pursuits/{pursuit_id}/withdraw", headers=headers)
        second = client.post(f"/pursuits/{pursuit_id}/withdraw", headers=headers)

        assert (first.status_code, second.status_code) == (204, 409), second.text
