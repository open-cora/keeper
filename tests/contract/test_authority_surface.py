"""Editing a policy over HTTP, through the app the process actually builds.

The unit tests exercise the handlers directly and the integration tests
exercise them against real SQL. Neither goes through a route, so neither
can see the two failures that live only there: a request field bound to
the wrong argument, and a domain error nobody registered a status code
for. Both leave every other tier green, and the second is a 500.

The permission sets here are built from `GOVERNING_COMMAND_NAMES`, so a
policy defined in this file stays the smallest legal one whatever joins
that set.
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.authority.aggregates.policy import GOVERNING_COMMAND_NAMES
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

pytestmark = pytest.mark.contract

_ADMINISTRATOR = uuid4()


def _governing_body(principal_id: UUID = _ADMINISTRATOR) -> list[dict[str, str]]:
    return [
        {"principal_id": str(principal_id), "command_name": name}
        for name in sorted(GOVERNING_COMMAND_NAMES)
    ]


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def _a_policy(client: TestClient, principal_id: UUID = _ADMINISTRATOR) -> str:
    response = client.post("/policies", json={"permissions": _governing_body(principal_id)})
    assert response.status_code == 201, response.text
    policy_id: str = response.json()["policy_id"]
    return policy_id


def test_posting_a_policy_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_policy(client)


def test_defining_a_policy_nobody_could_change_is_unprocessable(client: TestClient) -> None:
    """422 rather than 409: nothing stored conflicts, the shape is refused."""
    with client:
        response = client.post("/policies", json={"permissions": []})
    assert response.status_code == 422


def test_granting_a_permission_returns_no_content(client: TestClient) -> None:
    with client:
        policy_id = _a_policy(client)
        response = client.post(
            f"/policies/{policy_id}/permissions",
            json={"principal_id": str(uuid4()), "command_name": "RegisterActor"},
        )
    assert response.status_code == 204


def test_granting_the_same_permission_twice_is_a_conflict(client: TestClient) -> None:
    """The domain refusal, reached through the stack and mapped to a status.

    A decider raising the right error and a routes module that never
    learned about it both look correct in isolation, and together they
    are a 500.
    """
    body = {"principal_id": str(uuid4()), "command_name": "RegisterActor"}
    with client:
        policy_id = _a_policy(client)
        client.post(f"/policies/{policy_id}/permissions", json=body)
        second = client.post(f"/policies/{policy_id}/permissions", json=body)
    assert second.status_code == 409


def test_granting_under_a_policy_that_does_not_exist_is_a_not_found(client: TestClient) -> None:
    with client:
        response = client.post(
            f"/policies/{uuid4()}/permissions",
            json={"principal_id": str(uuid4()), "command_name": "RegisterActor"},
        )
    assert response.status_code == 404


def test_a_granted_permission_can_be_revoked_at_its_own_address(client: TestClient) -> None:
    """The pair in the path names the pair in the body that put it there.

    This is what the route can get wrong on its own. Both endpoints
    carry a principal id and a command name, and the revoke also carries
    the CALLER's id in a header dependency. A route binding the caller
    where the grantee belongs would grant and revoke happily in
    isolation and never address the same permission twice.
    """
    grantee, command = str(uuid4()), "RegisterActor"
    with client:
        policy_id = _a_policy(client)
        client.post(
            f"/policies/{policy_id}/permissions",
            json={"principal_id": grantee, "command_name": command},
        )
        response = client.delete(f"/policies/{policy_id}/permissions/{grantee}/{command}")
    assert response.status_code == 204


def test_revoking_a_permission_the_policy_never_held_is_a_conflict(client: TestClient) -> None:
    with client:
        policy_id = _a_policy(client)
        response = client.delete(f"/policies/{policy_id}/permissions/{uuid4()}/RegisterActor")
    assert response.status_code == 409


def test_revoking_under_a_policy_that_does_not_exist_is_a_not_found(client: TestClient) -> None:
    with client:
        response = client.delete(f"/policies/{uuid4()}/permissions/{uuid4()}/RegisterActor")
    assert response.status_code == 404


def test_revoking_the_last_way_to_change_a_policy_is_unprocessable(client: TestClient) -> None:
    """The governance guard, reached through the stack and given a status.

    422 and not 409 for the same reason defining an ungovernable policy
    is: nothing stored conflicts with the request. The rulebook refuses
    the shape it would be left in.
    """
    last = sorted(GOVERNING_COMMAND_NAMES)[0]
    with client:
        policy_id = _a_policy(client)
        response = client.delete(f"/policies/{policy_id}/permissions/{_ADMINISTRATOR}/{last}")
    assert response.status_code == 422


def test_revoking_the_same_permission_twice_is_a_conflict(client: TestClient) -> None:
    """The second call must not be absorbed, which a set difference would do."""
    grantee, command = str(uuid4()), "RegisterActor"
    address = f"/policies/{{}}/permissions/{grantee}/{command}"
    with client:
        policy_id = _a_policy(client)
        client.post(
            f"/policies/{policy_id}/permissions",
            json={"principal_id": grantee, "command_name": command},
        )
        assert client.delete(address.format(policy_id)).status_code == 204
        second = client.delete(address.format(policy_id))
    assert second.status_code == 409


def test_a_malformed_policy_id_is_rejected_before_the_handler(client: TestClient) -> None:
    """The path parameter is a UUID, so the router refuses a non-UUID."""
    with client:
        response = client.delete(f"/policies/not-a-uuid/permissions/{uuid4()}/RegisterActor")
    assert response.status_code == 422


def test_granting_the_system_principal_a_permission_is_unprocessable(client: TestClient) -> None:
    """The shortcut the aggregate refuses, refused at the door it arrives by."""
    with client:
        policy_id = _a_policy(client)
        response = client.post(
            f"/policies/{policy_id}/permissions",
            json={"principal_id": str(SYSTEM_PRINCIPAL_ID), "command_name": "RegisterActor"},
        )
    assert response.status_code == 422


def test_reading_a_policy_returns_the_pairs_it_permits(client: TestClient) -> None:
    grantee = str(uuid4())
    with client:
        policy_id = _a_policy(client)
        client.post(
            f"/policies/{policy_id}/permissions",
            json={"principal_id": grantee, "command_name": "RegisterActor"},
        )
        response = client.get(f"/policies/{policy_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["policy_id"] == policy_id
    assert {"principal_id": grantee, "command_name": "RegisterActor"} in body["permissions"]


def test_reading_a_policy_that_was_never_defined_is_a_not_found(client: TestClient) -> None:
    with client:
        response = client.get(f"/policies/{uuid4()}")
    assert response.status_code == 404


def test_a_grant_and_a_revocation_are_visible_to_the_next_read(client: TestClient) -> None:
    """The writes and the read agree, through the stack rather than by fold.

    The unit tests fold events in process. This is the one that would
    notice the read slice and the writing slices disagreeing about the
    stream type, which nothing else here can see.
    """
    pair = {"principal_id": str(uuid4()), "command_name": "RegisterActor"}
    with client:
        policy_id = _a_policy(client)
        client.post(f"/policies/{policy_id}/permissions", json=pair)
        after_grant = client.get(f"/policies/{policy_id}").json()["permissions"]
        client.delete(
            f"/policies/{policy_id}/permissions/{pair['principal_id']}/{pair['command_name']}"
        )
        after_revoke = client.get(f"/policies/{policy_id}").json()["permissions"]
    assert pair in after_grant
    assert pair not in after_revoke


def test_the_permissions_come_back_in_a_declared_order(client: TestClient) -> None:
    """A set has no order, so the wire must impose one.

    Without it a client polling this endpoint sees the same rulebook in
    a different order on a different process and cannot tell that from
    an edit. Eight pairs rather than two, because a handful of items can
    come out of a set in sorted order by luck.
    """
    with client:
        policy_id = _a_policy(client)
        for _ in range(8):
            client.post(
                f"/policies/{policy_id}/permissions",
                json={"principal_id": str(uuid4()), "command_name": "RegisterActor"},
            )
        permissions = client.get(f"/policies/{policy_id}").json()["permissions"]

    keys = [(p["principal_id"], p["command_name"]) for p in permissions]
    assert keys == sorted(keys)


def test_an_app_pointed_at_a_policy_that_does_not_exist_refuses_everything() -> None:
    """The enforcing adapter, reached through the whole application.

    `AUTHZ_POLICY_ID` set to an id with nothing behind it is the typo
    this deployment is most likely to make, and the answer is a shut
    door rather than an open one. It is also unrecoverable through the
    API, which is why the bootstrap is documented as authoring the
    policy first and restarting: the command that would fix this is one
    of the commands being refused.

    Its own client rather than the fixture, because the posture is set
    at boot and every other test in this file wants the permissive one.
    """
    enforcing = TestClient(create_app(settings=Settings(app_env="test", authz_policy_id=uuid4())))
    with enforcing:
        defined = enforcing.post("/policies", json={"permissions": _governing_body()})
        read = enforcing.get(f"/policies/{uuid4()}")

    assert defined.status_code == 403
    assert read.status_code == 403


def test_the_permissive_posture_is_what_the_other_tests_here_run_under() -> None:
    """Guard the test above: both postures must not answer the same way.

    Without this, a 403 from an application that refuses everything for
    an unrelated reason would read as evidence that the policy adapter
    was consulted.
    """
    with TestClient(create_app(settings=Settings(app_env="test"))) as permissive:
        response = permissive.post("/policies", json={"permissions": _governing_body()})
    assert response.status_code == 201
