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
from keeper.custody.aggregates.dataset import DATASET_MAX_FINDINGS
from keeper.infrastructure.settings import Settings
from keeper.shared.identifier import IDENTIFIER_VALUE_MAX_LENGTH

pytestmark = pytest.mark.contract

_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_REF = {"scheme": "tiled-node-path", "value": "raw/636de04a-2e43-4c1b"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(environment="test")))


def _an_acquisition(client: TestClient) -> tuple[str, str]:
    """An operation, a procedure running it, and one dispatch, over HTTP.

    The whole chain, because a dataset names a step and a step exists
    only inside an execution, so the registering route has something real
    to check against.
    """
    operation = client.post("/operations", json={"name": "count", "parameters_schema": _SCHEMA})
    assert operation.status_code == 201, operation.text
    procedure = client.post(
        "/procedures",
        json={
            "name": "one_scan",
            "beamline": "2-bm",
            "steps": [
                {
                    "kind": "run",
                    "operation_id": operation.json()["operation_id"],
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


def _a_dataset(client: TestClient, run: tuple[str, str]) -> str:
    execution_id, step_id = run
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
        "external_refs": [_REF],
        "description": None,
        "findings": [],
    }


_CENTRAL = {"scheme": "gpfs-file", "value": "/central/raw/636de04a.h5"}


def test_a_second_address_reads_back_beside_the_one_the_run_wrote(
    client: TestClient,
) -> None:
    """Both at once is the state a copy spends days in, not a transition."""
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))
        added = client.post(f"/datasets/{dataset_id}/addresses", json={"external_ref": _CENTRAL})
        read = client.get(f"/datasets/{dataset_id}")

    assert added.status_code == 204, added.text
    assert read.json()["external_refs"] == [_REF, _CENTRAL]


def test_an_address_the_dataset_already_holds_is_409(client: TestClient) -> None:
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))
        again = client.post(f"/datasets/{dataset_id}/addresses", json={"external_ref": _REF})

    assert again.status_code == 409, again.text


def test_registering_an_address_on_a_dataset_that_does_not_exist_is_404(
    client: TestClient,
) -> None:
    with client:
        response = client.post(f"/datasets/{uuid4()}/addresses", json={"external_ref": _CENTRAL})

    assert response.status_code == 404, response.text


def test_a_withdrawn_address_leaves_the_others_and_the_run_that_made_them(
    client: TestClient,
) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        client.post(f"/datasets/{dataset_id}/addresses", json={"external_ref": _CENTRAL})
        gone = client.post(
            f"/datasets/{dataset_id}/addresses/withdraw", json={"external_ref": _REF}
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert gone.status_code == 204, gone.text
    assert read.json() == {
        "dataset_id": dataset_id,
        "execution_id": execution_id,
        "step_id": step_id,
        "external_refs": [_CENTRAL],
        "description": None,
        "findings": [],
    }


def test_a_dataset_whose_last_address_is_withdrawn_still_names_its_run(
    client: TestClient,
) -> None:
    """The empty list is reachable over HTTP, and it is not an error."""
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        gone = client.post(
            f"/datasets/{dataset_id}/addresses/withdraw", json={"external_ref": _REF}
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert gone.status_code == 204, gone.text
    assert read.json()["external_refs"] == []
    assert read.json()["step_id"] == step_id


def test_withdrawing_an_address_the_dataset_does_not_hold_is_409(client: TestClient) -> None:
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))
        response = client.post(
            f"/datasets/{dataset_id}/addresses/withdraw", json={"external_ref": _CENTRAL}
        )

    assert response.status_code == 409, response.text


def test_an_address_whose_value_carries_slashes_needs_no_encoding_to_withdraw(
    client: TestClient,
) -> None:
    """The reason withdrawal is a POST with a body rather than a DELETE.

    A store's own spelling routinely carries path separators, and an
    encoded slash is the one piece of URL handling that differs between
    every proxy this will sit behind.
    """
    deep = {"scheme": "gpfs-file", "value": "/central/19bm/2026-10/a b/scan 034.h5"}
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))
        client.post(f"/datasets/{dataset_id}/addresses", json={"external_ref": deep})
        gone = client.post(
            f"/datasets/{dataset_id}/addresses/withdraw", json={"external_ref": deep}
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert gone.status_code == 204, gone.text
    assert read.json()["external_refs"] == [_REF]


def test_a_description_reads_back_with_the_copy_it_was_taken_of(client: TestClient) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        filed = client.post(
            f"/datasets/{dataset_id}/manifests",
            json={
                "external_ref": _REF,
                "convention": "dxchange",
                "entries": [
                    {
                        "path": "/exchange/data",
                        "extent": {"shape": [1800, 2048, 2048], "dtype": "uint16"},
                        "role": "projections",
                    },
                    {"path": "/measurement/sample"},
                ],
            },
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert filed.status_code == 204, filed.text
    described = read.json()["description"]
    assert described["external_ref"] == _REF
    assert described["convention"] == "dxchange"
    assert described["entries"] == [
        {
            "path": "/exchange/data",
            "extent": {"shape": [1800, 2048, 2048], "capacity": None, "dtype": "uint16"},
            "role": "projections",
        },
        {"path": "/measurement/sample", "extent": None, "role": None},
    ], (
        "an entry nobody measured carries no extent and an entry nobody named "
        "carries no role, and a reader that cannot see those absences cannot "
        "tell them from a zero"
    )


def test_an_entry_a_convention_expects_and_the_data_lacks_is_simply_absent(
    client: TestClient,
) -> None:
    """The failure this whole seam exists to make visible.

    A tomography scan whose rotation angles were never written cannot
    be reconstructed, and nothing notices today until somebody tries.
    The record notices by not holding the entry, which is why nothing
    on the way in may supply what a convention says should be there.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        client.post(
            f"/datasets/{dataset_id}/manifests",
            json={
                "external_ref": _REF,
                "convention": "dxchange",
                "entries": [{"path": "/exchange/data", "role": "projections"}],
            },
        )
        read = client.get(f"/datasets/{dataset_id}")

    paths = [entry["path"] for entry in read.json()["description"]["entries"]]
    assert paths == ["/exchange/data"]


def test_a_second_look_that_found_something_new_replaces_the_first(client: TestClient) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        body: dict[str, Any] = {
            "external_ref": _REF,
            "convention": "dxchange",
            "entries": [{"path": "/exchange/data", "role": "projections"}],
        }
        client.post(f"/datasets/{dataset_id}/manifests", json=body)
        again = client.post(
            f"/datasets/{dataset_id}/manifests",
            json={
                **body,
                "entries": [
                    {"path": "/exchange/data", "role": "projections"},
                    {"path": "/exchange/theta", "role": "projection-angles"},
                ],
            },
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert again.status_code == 204, again.text
    paths = [entry["path"] for entry in read.json()["description"]["entries"]]
    assert paths == ["/exchange/data", "/exchange/theta"]


def test_a_description_repeating_what_the_record_already_says_is_409(client: TestClient) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        body: dict[str, Any] = {
            "external_ref": _REF,
            "convention": "dxchange",
            "entries": [{"path": "/exchange/data", "role": "projections"}],
        }
        client.post(f"/datasets/{dataset_id}/manifests", json=body)
        again = client.post(f"/datasets/{dataset_id}/manifests", json=body)

    assert again.status_code == 409, again.text


def test_describing_a_copy_the_dataset_does_not_hold_is_409(client: TestClient) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        refused = client.post(
            f"/datasets/{dataset_id}/manifests",
            json={
                "external_ref": {"scheme": "gpfs-file", "value": "/central/raw/nobody-filed.h5"},
                "convention": "dxchange",
                "entries": [],
            },
        )

    assert refused.status_code == 409, refused.text


def test_describing_a_dataset_that_does_not_exist_is_404(client: TestClient) -> None:
    with client:
        refused = client.post(
            f"/datasets/{uuid4()}/manifests",
            json={"external_ref": _REF, "convention": "dxchange", "entries": []},
        )

    assert refused.status_code == 404, refused.text


def test_a_container_counted_by_two_numbers_is_400_rather_than_500(client: TestClient) -> None:
    """The one malformed shape this context owns, reaching its own handler.

    Without a dtype an entry describes a container, which is counted by
    one number. Two says nothing anybody meant, and the value object is
    what refuses it. Nothing but a route can show that the refusal
    arrives as a 400 rather than as an unhandled exception.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        refused = client.post(
            f"/datasets/{dataset_id}/manifests",
            json={
                "external_ref": _REF,
                "convention": "dxchange",
                "entries": [{"path": "/measurement", "extent": {"shape": [4, 2]}}],
            },
        )

    assert refused.status_code == 400, refused.text


def test_a_container_too_wide_to_describe_is_refused_at_the_boundary(
    client: TestClient,
) -> None:
    with client:
        execution_id, step_id = _an_acquisition(client)
        dataset_id = _a_dataset(client, (execution_id, step_id))
        refused = client.post(
            f"/datasets/{dataset_id}/manifests",
            json={
                "external_ref": _REF,
                "convention": "dxchange",
                "entries": [{"path": f"/exchange/data_{index}"} for index in range(65)],
            },
        )

    assert refused.status_code == 422, refused.text


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
    assert body["items"][0]["external_refs"] == [_REF]
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


def test_a_finding_reads_back_on_the_dataset_it_judges(client: TestClient) -> None:
    """The last of the three layers, over the real app.

    The address says where the data is, the description says what
    shapes are in it, and this says what somebody made of them. Only
    this tier shows whether a refusal the route declares has a status
    code registered for it, because a missing registration is a 500
    rather than a failing assertion anywhere else.
    """
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))

        recorded = client.post(
            f"/datasets/{dataset_id}/findings",
            json={"judgement": "projections-short-of-plan", "expected": 128, "arrived": 100},
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert recorded.status_code == 204, recorded.text
    assert read.json()["findings"] == [
        {"judgement": "projections-short-of-plan", "expected": 128, "arrived": 100}
    ]


def test_a_finding_against_a_dataset_nobody_registered_is_not_found(
    client: TestClient,
) -> None:
    with client:
        response = client.post(
            f"/datasets/{uuid4()}/findings",
            json={"judgement": "angles-never-recorded", "expected": 1, "arrived": 0},
        )

    assert response.status_code == 404, response.text


def test_a_finding_repeating_what_the_record_says_is_a_conflict(client: TestClient) -> None:
    body = {"judgement": "angles-never-recorded", "expected": 1, "arrived": 0}
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))

        client.post(f"/datasets/{dataset_id}/findings", json=body)
        again = client.post(f"/datasets/{dataset_id}/findings", json=body)

    assert again.status_code == 409, again.text


def test_the_same_judgement_on_different_counts_is_admitted_over_http(
    client: TestClient,
) -> None:
    """A second look after the data changed is news, not a redelivery."""
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))

        client.post(
            f"/datasets/{dataset_id}/findings",
            json={"judgement": "projections-short-of-plan", "expected": 128, "arrived": 100},
        )
        better = client.post(
            f"/datasets/{dataset_id}/findings",
            json={"judgement": "projections-short-of-plan", "expected": 128, "arrived": 128},
        )
        read = client.get(f"/datasets/{dataset_id}")

    assert better.status_code == 204, better.text
    assert read.json()["findings"] == [
        {"judgement": "projections-short-of-plan", "expected": 128, "arrived": 128}
    ]


def test_a_judgement_of_nothing_but_spaces_is_refused_as_malformed(
    client: TestClient,
) -> None:
    """The one path that reaches the value object's own refusal.

    A blank string is stopped by the request model, so the domain error
    would never be raised and its status registration would never be
    exercised. Whitespace passes the length bound and fails the value
    object, which is what proves the 400 is wired.
    """
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))

        response = client.post(
            f"/datasets/{dataset_id}/findings",
            json={"judgement": "   ", "expected": 1, "arrived": 0},
        )

    assert response.status_code == 400, response.text


def test_a_dataset_offered_more_judgements_than_it_may_carry_is_a_conflict(
    client: TestClient,
) -> None:
    with client:
        dataset_id = _a_dataset(client, _an_acquisition(client))
        for n in range(DATASET_MAX_FINDINGS):
            filled = client.post(
                f"/datasets/{dataset_id}/findings",
                json={"judgement": f"word-{n}", "expected": 1, "arrived": 1},
            )
            assert filled.status_code == 204, filled.text

        over = client.post(
            f"/datasets/{dataset_id}/findings",
            json={"judgement": "one-too-many", "expected": 1, "arrived": 1},
        )

    assert over.status_code == 409, over.text
