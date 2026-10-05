"""Reading the log over HTTP, through the app the process builds.

The log read is the one route in this system that is not a slice, so
nothing else in the contract tier covers it: there is no tool twin to
compare against and no bounded context whose surface test would reach it.

What is walked here is the part that lives only at the route. The two
grants decide which streams come back, and whether they are unioned or
ordered is invisible from any other tier. The cursor round trip is the
other: a page hands back a token and the next request has to resume from
it rather than from the beginning.
"""

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.event_log import (
    READ_EVENT_LOG,
    READ_FULL_EVENT_LOG,
    get_deps,
)
from keeper.api.main import create_app
from keeper.infrastructure.ports import Allow, Deny
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID

if TYPE_CHECKING:
    from fastapi import FastAPI

    from keeper.infrastructure.kernel import Kernel

pytestmark = pytest.mark.contract

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _GrantsOnly:
    """Allows exactly the command names it was built with."""

    def __init__(self, *command_names: str) -> None:
        self._granted = frozenset(command_names)

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> Allow | Deny:
        _ = (principal_id, surface_id, beamline)
        if command_name in self._granted:
            return Allow()
        return Deny(reason=f"{command_name} not granted")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(environment="test")))


def _grant(client: TestClient, *command_names: str) -> None:
    """Narrow the app to these grants, leaving every other route open.

    The override replaces the kernel the log route reads, so writes made
    through the other routes still run under the permissive test wiring
    and the test can author the events it then tries to read.
    """
    app = cast("FastAPI", client.app)
    narrowed: Kernel = replace(app.state.deps, authz=_GrantsOnly(*command_names))
    app.dependency_overrides[get_deps] = lambda: narrowed


def _an_operation(client: TestClient, name: str = "count") -> None:
    response = client.post("/operations", json={"name": name, "parameters_schema": _SCHEMA})
    assert response.status_code == 201, response.text


def _an_actor(client: TestClient) -> None:
    response = client.post("/actors", json={"actor_id": str(uuid4())})
    assert response.status_code in (200, 201), response.text


def _stream_types(body: dict[str, Any]) -> set[str]:
    return {item["stream_type"] for item in body["items"]}


def test_reading_an_empty_log_returns_no_items_and_no_cursor(client: TestClient) -> None:
    with client:
        response = client.get("/events")

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_an_appended_event_appears_in_the_log(client: TestClient) -> None:
    with client:
        _an_operation(client)
        response = client.get("/events")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["event_type"] for item in body["items"]] == ["OperationDefined"]
    assert body["next_cursor"] is not None


def test_the_log_carries_the_envelope_and_the_payload(client: TestClient) -> None:
    with client:
        _an_operation(client, name="tomo")
        response = client.get("/events")

    event = response.json()["items"][0]
    assert event["stream_type"] == "Operation"
    assert event["payload"]["operation_name"] == "tomo"
    assert event["metadata"] == {"command": "DefineOperation"}
    assert event["correlation_id"]
    assert event["position"] >= 1


def test_resuming_from_a_cursor_returns_only_what_followed(client: TestClient) -> None:
    with client:
        _an_operation(client, name="first")
        first = client.get("/events").json()
        _an_operation(client, name="second")
        resumed = client.get("/events", params={"after": first["next_cursor"]}).json()

    assert [item["payload"]["operation_name"] for item in first["items"]] == ["first"]
    assert [item["payload"]["operation_name"] for item in resumed["items"]] == ["second"]


def test_a_cursor_at_the_head_returns_an_empty_page(client: TestClient) -> None:
    with client:
        _an_operation(client)
        first = client.get("/events").json()
        again = client.get("/events", params={"after": first["next_cursor"]}).json()

    assert again == {"items": [], "next_cursor": None}


def test_limit_bounds_the_page_and_the_cursor_continues_it(client: TestClient) -> None:
    with client:
        _an_operation(client, name="one")
        _an_operation(client, name="two")
        page = client.get("/events", params={"limit": 1}).json()
        rest = client.get("/events", params={"after": page["next_cursor"]}).json()

    assert [item["payload"]["operation_name"] for item in page["items"]] == ["one"]
    assert [item["payload"]["operation_name"] for item in rest["items"]] == ["two"]


def test_a_cursor_that_did_not_come_from_a_response_is_refused(client: TestClient) -> None:
    with client:
        response = client.get("/events", params={"after": "not-a-cursor"})

    assert response.status_code == 422, response.text


def test_the_general_grant_withholds_the_administrators_streams(client: TestClient) -> None:
    with client:
        _an_operation(client)
        _an_actor(client)
        _grant(client, READ_EVENT_LOG)
        body = client.get("/events").json()

    assert "Operation" in _stream_types(body)
    assert "Actor" not in _stream_types(body)


def test_the_full_grant_includes_the_administrators_streams(client: TestClient) -> None:
    with client:
        _an_operation(client)
        _an_actor(client)
        _grant(client, READ_FULL_EVENT_LOG)
        body = client.get("/events").json()

    assert {"Operation", "Actor"} <= _stream_types(body)


def test_the_full_grant_alone_still_returns_the_general_streams(client: TestClient) -> None:
    """The two grants union rather than ordering, so the narrower one is
    not a prerequisite for the wider one."""
    with client:
        _an_operation(client)
        _grant(client, READ_FULL_EVENT_LOG)
        body = client.get("/events").json()

    assert "Operation" in _stream_types(body)


def test_a_principal_holding_neither_grant_is_refused(client: TestClient) -> None:
    with client:
        _an_operation(client)
        _grant(client, "SomethingElse")
        response = client.get("/events")

    assert response.status_code == 403, response.text
