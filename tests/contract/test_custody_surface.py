"""Registering and reading a dataset over HTTP, through the app the process builds.

The unit tests exercise the handlers directly, so neither they nor the
integration tier can see the two failures that live only on a route: a
request field bound to the wrong argument, and a domain error nobody
registered a status code for. Both leave every other tier green, and the
second is a 500.

That second one matters more here than anywhere else in the tree, because
this context deliberately registers three handlers and relies on another
context for four more. `ExecutionNotFoundError`,
`ExecutionStepNotFoundError`, `InvalidIdentifierError` and
`InvalidOccurredAtError` all reach a Custody route and none is registered
by Custody. Whether that reliance actually holds is not something the
source can state, so it is walked below.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.infrastructure.settings import Settings
from keeper.shared.identifier import IDENTIFIER_VALUE_MAX_LENGTH

pytestmark = pytest.mark.contract

_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_REF = {"scheme": "tiled-node-path", "value": "raw/636de04a-2e43-4c1b"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def _an_acquisition(client: TestClient) -> tuple[str, str]:
    """A plan, a procedure acquiring it, and one dispatch, over HTTP.

    The whole chain, because a dataset names a step and a step exists
    only inside an execution, so the registering route has something real
    to check against.
    """
    plan = client.post("/plans", json={"name": "count", "parameters_schema": _SCHEMA})
    assert plan.status_code == 201, plan.text
    procedure = client.post(
        "/procedures",
        json={
            "name": "one_scan",
            "beamline": "2-bm",
            "steps": [
                {
                    "kind": "acquire",
                    "plan_id": plan.json()["plan_id"],
                    "parameters": {},
                    "scopes": ["2bmb:det:"],
                }
            ],
        },
    )
    assert procedure.status_code == 201, procedure.text
    dispatched = client.post("/executions", json={"procedure_id": procedure.json()["procedure_id"]})
    assert dispatched.status_code == 201, dispatched.text
    execution_id: str = dispatched.json()["execution_id"]
    read = client.get(f"/executions/{execution_id}")
    assert read.status_code == 200, read.text
    step_id: str = read.json()["steps"][0]["step_id"]
    return execution_id, step_id


def _a_dataset(client: TestClient, acquisition: tuple[str, str]) -> str:
    execution_id, step_id = acquisition
    response = client.post(
        "/datasets",
        json={"execution_id": execution_id, "step_id": step_id, "external_ref": _REF},
    )
    assert response.status_code == 201, response.text
    dataset_id: str = response.json()["dataset_id"]
    return dataset_id


def test_posting_a_dataset_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_dataset(client, _an_acquisition(client))


def test_a_registered_dataset_reads_back_with_its_step_and_reference(
    client: TestClient,
) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        response = client.get(f"/datasets/{dataset_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "dataset_id": dataset_id,
        "execution_id": execution_id,
        "step_id": step_id,
        "external_ref": _REF,
    }


def test_reading_an_unregistered_dataset_is_404(client: TestClient) -> None:
    with client:
        response = client.get(f"/datasets/{uuid4()}")

    assert response.status_code == 404, response.text


def test_citing_an_execution_that_does_not_exist_is_404(client: TestClient) -> None:
    """The sibling's error class, mapped by the sibling's registration."""
    with client:
        response = client.post(
            "/datasets",
            json={"execution_id": str(uuid4()), "step_id": str(uuid4()), "external_ref": _REF},
        )

    assert response.status_code == 404, response.text


def test_a_whitespace_only_reference_value_is_400_rather_than_500(
    client: TestClient,
) -> None:
    """The check Pydantic cannot make, so the value object makes it.

    A string of spaces is long enough for `min_length=1` and empty once
    trimmed, so it reaches `Identifier` and comes back as the shared
    400. If nobody had registered that class this would be a 500, which
    is the whole reason this case is walked over a route.
    """
    with client:
        response = client.post(
            "/datasets",
            json={
                **dict(zip(("execution_id", "step_id"), _an_acquisition(client), strict=True)),
                "external_ref": {"scheme": "tiled-node-path", "value": "   "},
            },
        )

    assert response.status_code == 400, response.text


def test_an_over_long_reference_value_is_refused_at_the_boundary(
    client: TestClient,
) -> None:
    """The check Pydantic can make, so it never reaches a command."""
    with client:
        response = client.post(
            "/datasets",
            json={
                **dict(zip(("execution_id", "step_id"), _an_acquisition(client), strict=True)),
                "external_ref": {
                    "scheme": "tiled-node-path",
                    "value": "x" * (IDENTIFIER_VALUE_MAX_LENGTH + 1),
                },
            },
        )

    assert response.status_code == 422, response.text


def test_a_reported_time_without_an_offset_is_400_rather_than_500(
    client: TestClient,
) -> None:
    """Also the sibling's error class, reached through the borrowed helper."""
    with client:
        response = client.post(
            "/datasets",
            json={
                **dict(zip(("execution_id", "step_id"), _an_acquisition(client), strict=True)),
                "external_ref": _REF,
                "occurred_at": "2026-09-19T14:30:00",
            },
        )

    assert response.status_code == 400, response.text


def test_listing_by_step_returns_what_that_acquisition_produced(client: TestClient) -> None:
    """The question this context exists for, over the surface that answers it."""
    with client:
        mine = _an_acquisition(client)
        theirs = _an_acquisition(client)
        wanted = _a_dataset(client, mine)
        client.post(
            "/datasets",
            json={
                "execution_id": theirs[0],
                "step_id": theirs[1],
                "external_ref": {"scheme": "tiled-node-path", "value": "raw/theirs"},
            },
        )
        response = client.get("/datasets", params={"step_id": mine[1]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["dataset_id"] for item in body["items"]] == [wanted]
    assert body["items"][0]["external_ref"] == _REF
    assert body["next_cursor"] is None


def test_listing_a_step_that_produced_nothing_is_an_empty_page(client: TestClient) -> None:
    """Empty and 200, not 404. A run with no data is an answer."""
    with client:
        response = client.get("/datasets", params={"step_id": str(uuid4())})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_a_cursor_this_system_did_not_issue_is_refused(client: TestClient) -> None:
    """Registered by the composition root rather than by this context, so
    a route reaching it is the only way to know the mapping holds."""
    with client:
        response = client.get("/datasets", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422, response.text


def test_a_limit_over_the_maximum_is_refused_at_the_boundary(client: TestClient) -> None:
    with client:
        response = client.get("/datasets", params={"limit": 1000})

    assert response.status_code == 422, response.text


def test_replaying_an_idempotency_key_returns_the_first_dataset(
    client: TestClient,
) -> None:
    """The only thing standing between a redelivered report and two records.

    Nothing in this context refuses a duplicate on its own, because one
    stream cannot see another, so this is not a convenience here the way
    it is elsewhere.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        body = {"execution_id": execution_id, "step_id": step_id, "external_ref": _REF}
        headers = {"Idempotency-Key": "register-dataset:raw/636de04a-2e43-4c1b"}
        first = client.post("/datasets", json=body, headers=headers)
        second = client.post("/datasets", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["dataset_id"] == second.json()["dataset_id"]


def test_the_same_key_with_a_different_body_is_refused(client: TestClient) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        headers = {"Idempotency-Key": "register-dataset:raw/636de04a-2e43-4c1b"}
        client.post(
            "/datasets",
            json={"execution_id": execution_id, "step_id": step_id, "external_ref": _REF},
            headers=headers,
        )
        second = client.post(
            "/datasets",
            json={
                "execution_id": execution_id,
                "step_id": step_id,
                "external_ref": {"scheme": "tiled-node-path", "value": "proc/636de04a"},
            },
            headers=headers,
        )

    assert second.status_code == 422, second.text
