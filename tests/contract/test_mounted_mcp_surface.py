"""The tools a real client sees, asked of the mounted application.

Its sibling `test_access_mcp_tools.py` checks the registrar: it builds a
server of its own, calls the registration function, and reads the tools
back. That is the right subject for it, and its docstring says plainly
that the mount is "a single line in `create_app` and a separate
concern". The separate concern had no owner. Deleting
`register_access_tools(...)` from `create_app` survived the whole
contract and architecture suite, and the application would have served
an empty tool list to every MCP client while 575 tests passed.

So this file asks the mounted app, over the wire, the way a client
would: initialize, notify, then `tools/list`. The expected names are
spelled out here rather than imported. Pulling them from
`register_access_tools` would build both sides of the comparison from
the registrar and agree with it however wrong the mount was.

That rule is about the EXPECTED side of a comparison, not about imports
in general. The Authority execution imports `GOVERNING_COMMAND_NAMES` to
build a policy the domain will accept, which is an input rather than an
answer, and spelling that out would make this file fail confusingly the
day the set grows.

Slow by this tier's standards, because a full application boots for it,
so each test here earns its place separately.

The two executions call tools rather than listing them. Listing proves the
mount; it says nothing about the bodies, and a tool body is a second
copy of what a route does: build the input from the arguments, call the
handler, shape the answer. Nothing else in this repository executes one,
so a tool that dropped a field, read the wrong argument or returned an
unordered set would be invisible on the surface this project pairs with
HTTP as an equal.

One execution per bounded context, rather than one per tool, because the app
boots for each test here and an execution amortises that. Between them every
published tool runs at least once, which is the bar: the first thing
that ever executed one of these bodies found a bug in it.

What an execution cannot see is what a tool passes INWARD. The calling
principal comes from the MCP context and the surface from a constant,
and neither is echoed in any response, so nothing here would notice a
tool handing the handler the wrong one.
"""

import ast
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.authority.aggregates.policy import GOVERNING_COMMAND_NAMES
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

TOOLS_A_CLIENT_SHOULD_SEE = frozenset(
    {
        "register_actor",
        "deactivate_actor",
        "reactivate_actor",
        "get_actor",
        "define_policy",
        "grant_permission",
        "revoke_permission",
        "get_policy",
        "define_plan",
        "define_procedure",
        "get_plan",
        "get_procedure",
        "list_plans",
        "list_procedures",
        "claim_execution",
        "dispatch_execution",
        "report_step",
        "report_step_run",
        "end_execution",
        "get_execution",
        "list_executions",
        "register_dataset",
        "get_dataset",
        "list_datasets",
        "make_proposal",
        "get_proposal",
        "take_proposal",
        "list_proposals",
        "register_device",
        "fault_device",
        "recover_device",
        "retire_device",
        "get_device",
        "list_devices",
    }
)
"""Spelled out rather than imported, so this side is independent.

A bounded context publishing tools adds them here, in the commit that
mounts it.
"""

_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _result(response_text: str) -> dict[str, Any]:
    """The JSON-RPC result carried in a server-sent-events response body."""
    for line in response_text.splitlines():
        if line.startswith("data: "):
            payload: dict[str, Any] = json.loads(line.removeprefix("data: "))
            return payload.get("result", {})
    pytest.fail(f"no SSE data frame in the response:\n{response_text[:400]}")


def test_the_mounted_mcp_endpoint_publishes_every_tool_a_client_needs() -> None:
    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        opened = client.post(
            "/mcp/",
            headers=_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "contract-test", "version": "0"},
                },
            },
        )
        assert opened.status_code == 200, f"the MCP endpoint refused to open: {opened.text[:200]}"
        session = opened.headers.get("mcp-session-id")
        assert session, "the server opened no session, so the mount is not a live MCP endpoint"

        live = {**_HEADERS, "mcp-session-id": session}
        client.post(
            "/mcp/", headers=live, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        listed = client.post(
            "/mcp/", headers=live, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        assert listed.status_code == 200

    published = frozenset(tool["name"] for tool in _result(listed.text)["tools"])
    assert published == TOOLS_A_CLIENT_SHOULD_SEE, (
        "The mounted MCP surface is not what a client should see.\n"
        f"  Missing:   {sorted(TOOLS_A_CLIENT_SHOULD_SEE - published)}\n"
        f"  Unexpected: {sorted(published - TOOLS_A_CLIENT_SHOULD_SEE)}\n"
        "A tool registered on a server that is never mounted, or mounted on a "
        "server the app does not serve, looks correct everywhere except here."
    )


def _open_session(client: TestClient) -> dict[str, str]:
    """Initialize an MCP session and return the headers that keep it."""
    opened = client.post(
        "/mcp/",
        headers=_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "contract-test", "version": "0"},
            },
        },
    )
    assert opened.status_code == 200, f"the MCP endpoint refused to open: {opened.text[:200]}"
    session = opened.headers.get("mcp-session-id")
    assert session, "the server opened no session, so the mount is not a live MCP endpoint"
    live = {**_HEADERS, "mcp-session-id": session}
    client.post(
        "/mcp/", headers=live, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    return live


def _call(client: TestClient, live: dict[str, str], tool: str, **arguments: Any) -> dict[str, Any]:
    """Invoke one tool and return its structured result.

    The third parameter is `tool` and not `name` because a tool argument
    called `name` is ordinary, and one that collides with this helper's
    own parameter cannot be passed at all. `define_plan` takes one. The
    name this helper is given is the tool's; the names after it are the
    tool's arguments, and nothing should have to spell one differently
    to get it through.
    """
    response = client.post(
        "/mcp/",
        headers=live,
        json={
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text[:300]
    result = _result(response.text)
    assert not result.get("isError"), f"{tool} failed: {result}"
    structured: dict[str, Any] = result["structuredContent"]
    return structured


def test_a_client_can_write_and_read_a_policy_over_the_mcp_surface() -> None:
    """Every Authority tool body executed, not just published.

    The read is what the ordering assertion is for. A set has no order,
    so the tool imposes one, and it imposes it in its own code rather
    than sharing the route's. Eight pairs, because a handful can come
    out of a set in sorted order by luck.

    The revoke at the end takes back a pair this walk granted, named
    rather than picked out of the response. The first version revoked
    whichever permission sorted last, which is the administrator's
    governing one about one time in eight, and the governance guard
    refuses that: a flake, not a failure, and the sort of test that gets
    re-run until it passes.

    A revoke tool wired to the grant handler, or one naming a pair the
    policy does not hold, fails on the count or on `isError` rather than
    passing quietly.
    """
    administrator = str(uuid4())
    governing = [
        {"principal_id": administrator, "command_name": name}
        for name in sorted(GOVERNING_COMMAND_NAMES)
    ]

    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        live = _open_session(client)
        defined = _call(client, live, "define_policy", permissions=governing)
        policy_id = defined["policy_id"]
        granted = [str(uuid4()) for _ in range(8)]
        for principal_id in granted:
            _call(
                client,
                live,
                "grant_permission",
                policy_id=policy_id,
                principal_id=principal_id,
                command_name="RegisterActor",
            )
        read = _call(client, live, "get_policy", policy_id=policy_id)

        taken_back = {"principal_id": granted[0], "command_name": "RegisterActor"}
        _call(client, live, "revoke_permission", policy_id=policy_id, **taken_back)
        after = _call(client, live, "get_policy", policy_id=policy_id)

    assert read["policy_id"] == policy_id
    keys = [(p["principal_id"], p["command_name"]) for p in read["permissions"]]
    assert keys == sorted(keys), "a set has no order, so the tool must impose one"
    assert len(keys) == len(governing) + 8

    assert taken_back in read["permissions"]
    assert taken_back not in after["permissions"]
    assert len(after["permissions"]) == len(keys) - 1


def test_a_client_can_switch_an_actor_on_and_off_over_the_mcp_surface() -> None:
    """Every Access tool body executed, not just published.

    The switch is walked in both directions on purpose. Deactivate and
    reactivate take the same argument and hand back the same shape, so a
    bundle field wired to the wrong handler, or one registrar closure
    reused for both, serves them from one slice. That shows up here as
    the second call failing on `isError`, because the domain refuses
    deactivating an actor twice, and as `active` never coming back.

    `register_actor` takes no arguments and mints the id, so the id
    every later call uses had to come out of the first response. A tool
    that echoed an input instead of returning what the handler produced
    has nothing to echo.
    """
    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        live = _open_session(client)
        actor_id = _call(client, live, "register_actor")["actor_id"]
        fresh = _call(client, live, "get_actor", actor_id=actor_id)
        _call(client, live, "deactivate_actor", actor_id=actor_id)
        switched_off = _call(client, live, "get_actor", actor_id=actor_id)
        _call(client, live, "reactivate_actor", actor_id=actor_id)
        switched_on = _call(client, live, "get_actor", actor_id=actor_id)

    assert fresh == {"actor_id": actor_id, "active": True}
    assert switched_off == {"actor_id": actor_id, "active": False}
    assert switched_on == {"actor_id": actor_id, "active": True}


def test_a_client_can_write_and_read_a_plan_over_the_mcp_surface() -> None:
    """Every Execution tool body executed, not just published.

    The schema is what the read is checked on, and it is checked whole.
    A caller validating a request locally has to be validating against
    the same document this system will validate against, so a tool that
    rebuilt the schema from a parsed form, or dropped a keyword it did
    not recognise, would be handing out a contract nothing enforces.
    That shows up here as an inequality, not as a missing field.

    `define_plan` mints the id, so the id the read uses had to come out
    of the first response. A tool that echoed an input instead of
    returning what the handler produced has nothing to echo.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
        "required": ["exposure_seconds"],
    }

    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        live = _open_session(client)
        defined = _call(client, live, "define_plan", name="count", parameters_schema=schema)
        plan_id = defined["plan_id"]
        read = _call(client, live, "get_plan", plan_id=plan_id)

        # A second plan under the same name, because that is allowed and
        # because a lookup returning one of two is the failure a caller
        # cannot see. Its schema differs, which is the whole reason the
        # two are separate plans rather than one.
        narrower = {**schema, "properties": {"exposure_seconds": {"type": "number", "minimum": 1}}}
        second = _call(client, live, "define_plan", name="count", parameters_schema=narrower)
        found = _call(client, live, "list_plans", name="count")

    assert read == {"plan_id": plan_id, "name": "count", "parameters_schema": schema}
    assert {item["plan_id"] for item in found["items"]} == {plan_id, second["plan_id"]}, (
        "a name lookup must return every plan written down under it; returning "
        "one of two would choose for the caller on an ordering nobody asked about"
    )
    assert found["next_cursor"] is None


def test_a_procedure_composed_over_mcp_reads_back_with_every_step_it_was_given() -> None:
    """Compose, read, list, over the tool surface only.

    The steps go out as a discriminated union and have to come back as
    one. A surface that flattened the two kinds to a common shape, or
    dropped the parameters of an acquisition because a move has none,
    would hand a caller a routine that is not the one it composed. That
    shows up here as an inequality on the whole list.

    The acquisition cites a plan defined in the same session, because a
    procedure citing a plan that does not exist is refused, which is the
    check that makes a procedure more than a list of strings.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
        "required": ["exposure_seconds"],
    }
    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        live = _open_session(client)
        plan_id = _call(client, live, "define_plan", name="count", parameters_schema=schema)[
            "plan_id"
        ]
        steps = [
            {"kind": "move", "record": "2bmb:m1", "to": 12.5},
            {
                "kind": "acquire",
                "plan_id": plan_id,
                "parameters": {"exposure_seconds": 0.2},
                "scopes": ["2bmb:m1", "2bmb:det:"],
            },
        ]
        composed = _call(
            client, live, "define_procedure", name="tomography", beamline="2-bm", steps=steps
        )
        procedure_id = composed["procedure_id"]
        read = _call(client, live, "get_procedure", procedure_id=procedure_id)
        found = _call(client, live, "list_procedures", name="tomography")

    assert read["procedure_id"] == procedure_id
    assert read["name"] == "tomography"
    step_ids = [step.pop("step_id") for step in read["steps"]]
    assert read["steps"] == steps
    assert len(set(step_ids)) == 2, (
        "each step is named when it is composed, and an execution of this "
        "procedure cites one of these rather than a position in the list"
    )
    (listed,) = found["items"]
    assert listed["procedure_id"] == procedure_id
    assert listed["step_count"] == 2, (
        "a listing carries how long the routine is, because it drops the steps themselves"
    )


def test_a_client_can_dispatch_and_follow_an_execution_over_the_mcp_surface() -> None:
    """The remaining Execution tool bodies executed, not just published.

    The walk goes plan, procedure, execution, because each needs the one
    before it and none of them can be faked: those are the cross-aggregate
    reads exercised here through two surfaces rather than through a
    handler call.

    The step list goes in as a list of dictionaries with a discriminator
    and comes back as rendered sentences. The route parses that union
    from a request model and the tool does not, so a tool wired to the
    route's shape would fail to accept the argument at all.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
        "required": ["exposure_seconds"],
    }

    with TestClient(create_app(settings=Settings(app_env="test"))) as client:
        live = _open_session(client)
        plan_id = _call(client, live, "define_plan", name="count", parameters_schema=schema)[
            "plan_id"
        ]

        # Custody rides along on this walk rather than booting the
        # application again. A dataset names the step that produced it, so
        # it needs a dispatched execution rather than a run, and the
        # cheapest real one is a procedure of a single acquisition. The
        # cross-context read is exercised here through two surfaces rather
        # than through a handler call, the same way the plan read above is.
        # Custody rides along on this walk rather than booting the
        # application again. A dataset names the step that produced it, so
        # it needs a dispatched execution rather than a run, and the
        # cheapest real one is a procedure of a single acquisition. The
        # cross-context read is exercised here through two surfaces rather
        # than through a handler call, the same way the plan read above is.
        held_procedure = _call(
            client,
            live,
            "define_procedure",
            name="one_scan",
            beamline="2-bm",
            steps=[
                {
                    "kind": "acquire",
                    "plan_id": plan_id,
                    "parameters": {"exposure_seconds": 0.1},
                    "scopes": ["2bmb:det:"],
                }
            ],
        )["procedure_id"]
        held_execution = _call(client, live, "dispatch_execution", procedure_id=held_procedure)[
            "execution_id"
        ]
        produced_by = _call(client, live, "get_execution", execution_id=held_execution)["steps"][0][
            "step_id"
        ]
        registered = _call(
            client,
            live,
            "register_dataset",
            execution_id=held_execution,
            step_id=produced_by,
            external_ref_scheme="tiled-node-path",
            external_ref_value="raw/uid-completing",
        )
        dataset_id = registered["dataset_id"]
        held = _call(client, live, "get_dataset", dataset_id=dataset_id)
        produced = _call(client, live, "list_datasets", step_id=produced_by)

        # Counsel rides along for the same reason Custody does, and it
        # closes the loop the other two halves of this walk opened: a
        # proposal of the same plan, and the acquisition that took it.
        # The step is the one Custody just registered data against, which
        # is the shape the model asserts: one acquisition ran the plan,
        # produced the data, and answered the advice. The proposer is
        # what only this surface can show, because no request field
        # carries one.
        proposed = _call(client, live, "make_proposal", plan_id=plan_id, parameters={})
        proposal_id = proposed["proposal_id"]
        open_proposal = _call(client, live, "get_proposal", proposal_id=proposal_id)
        _call(
            client,
            live,
            "take_proposal",
            proposal_id=proposal_id,
            execution_id=held_execution,
            step_id=produced_by,
        )
        advised = _call(client, live, "get_proposal", proposal_id=proposal_id)

        # The read that needs no id, and the one the context exists for.
        # Asked after the take, so the answer has to come from a row that
        # moved rather than from one that was only ever inserted.
        still_open = _call(client, live, "list_proposals", is_open=True)
        acted_on = _call(client, live, "list_proposals", is_open=False)

        # Equipment rides along too, and unlike the three legs above it
        # borrows nothing from them: a device is not tied to a run, so
        # this is the one context here whose execution could stand alone. It
        # is on this walk anyway, because each test in this file boots
        # the application and an execution of its own would double that for no
        # coverage.
        #
        # The order is the order an adapter works in. It holds an address
        # and no id, so it resolves first and reports afterwards, and the
        # resolution is the step that makes every later call possible.
        enrolled = _call(
            client,
            live,
            "register_device",
            external_ref_scheme="epics-prefix",
            external_ref_value="2bmb:m1",
            name="sample x translation",
        )
        device_id = enrolled["device_id"]
        resolved = _call(
            client,
            live,
            "list_devices",
            external_ref_scheme="epics-prefix",
            external_ref_value="2bmb:m1",
        )
        _call(client, live, "fault_device", device_id=device_id)
        while_faulted = _call(client, live, "get_device", device_id=device_id)["status"]
        _call(client, live, "recover_device", device_id=device_id)
        after_recovery = _call(client, live, "get_device", device_id=device_id)["status"]
        _call(client, live, "retire_device", device_id=device_id)
        after_retirement = _call(client, live, "get_device", device_id=device_id)["status"]

        # The execution leg. An execution now cites a procedure, so this borrows the
        # one composed earlier on this same execution of the surface rather
        # than standing alone.
        #
        # Three steps and only two reported, then an ending. That is the
        # shape a driver killed mid-procedure leaves behind, and it is
        # the one case the write side has to accept rather than refuse.
        walk_procedure = _call(
            client,
            live,
            "define_procedure",
            name="align_then_scan",
            beamline="2-bm",
            steps=[
                {"kind": "move", "record": "2bmb:m1", "to": 0.0},
                {"kind": "move", "record": "2bmb:m2", "to": 5.0},
                {"kind": "move", "record": "2bmb:m3", "to": 1.0},
            ],
        )["procedure_id"]
        dispatched = _call(client, live, "dispatch_execution", procedure_id=walk_procedure)
        execution_id = dispatched["execution_id"]
        claimed = _call(client, live, "claim_execution", execution_id=execution_id)
        stepped = [
            _call(client, live, "report_step", execution_id=execution_id, index=0, outcome="Done"),
            _call(
                client,
                live,
                "report_step",
                execution_id=execution_id,
                index=1,
                outcome="Done",
                engine_reference="uid-from-the-engine",
            ),
        ]
        # The engine's own account of the step that opened a run, which
        # reaches this system from a different client than the driver.
        acquiring = _call(client, live, "get_execution", execution_id=execution_id)["steps"][1][
            "step_id"
        ]
        _call(
            client,
            live,
            "report_step_run",
            execution_id=execution_id,
            step_id=acquiring,
            reported="Started",
            engine_reference="uid-from-the-engine",
        )
        _call(
            client,
            live,
            "report_step_run",
            execution_id=execution_id,
            step_id=acquiring,
            reported="Failed",
        )
        midway = _call(client, live, "get_execution", execution_id=execution_id)
        closed = _call(client, live, "end_execution", execution_id=execution_id)
        after_closing = _call(client, live, "get_execution", execution_id=execution_id)

        # The read that needs no execution id: someone asking how a routine
        # went, every time it was run.
        recovered = _call(client, live, "list_executions", procedure_id=walk_procedure)

    assert stepped == [
        {"execution_id": execution_id, "index": 0},
        {"execution_id": execution_id, "index": 1},
    ], (
        "each step tool echoes the execution and the index it reported, because an "
        "index alone names nothing"
    )
    assert [step["outcome"] for step in midway["steps"]] == ["Done", "Done", None], (
        "a step nothing has reported reads as null rather than as skipped; "
        "skipped means the execution passed it over, null means nothing was said"
    )
    assert midway["steps"][1]["engine_reference"] == "uid-from-the-engine", (
        "the engine's name for the run a step opened is the only join between "
        "an execution and what an engine recorded"
    )
    assert (midway["steps"][1]["outcome"], midway["steps"][1]["engine_state"]) == (
        "Done",
        "Failed",
    ), (
        "two observers of one step, kept apart. The driver's call returned and "
        "the engine says the run broke, and collapsing those would make this "
        "system pick a winner between two claims it cannot check"
    )
    assert midway["steps"][0]["engine_state"] is None, (
        "a move opens no run, so there is nothing for an engine to report"
    )
    assert (midway["status"], after_closing["status"]) == ("Running", "Ended"), (
        "an execution with a step reported is running whatever else is true of it, "
        "and ending is the only terminal"
    )
    assert claimed == {"execution_id": execution_id}, (
        "claiming a dispatch is what says something took the work up, and a "
        "dispatch nothing ever claimed is the failure the status exists for"
    )
    assert [item["execution_id"] for item in recovered["items"]] == [execution_id], (
        "listing by procedure must find every execution dispatched for it, which "
        "is how anyone asks how a routine has been going"
    )
    assert (
        recovered["items"][0]["reported_count"],
        recovered["items"][0]["step_count"],
    ) == (2, 3), (
        "a summary has to show the gap a closed execution left rather than close "
        "it, because that gap is what an abandoned execution looks like"
    )
    assert closed == {"execution_id": execution_id}, (
        "an execution with a step still unreported must still close; refusing that "
        "would leave the executions that most need closing as the ones that cannot"
    )
    assert [item["proposal_id"] for item in acted_on["items"]] == [proposal_id], (
        "a proposal an acquisition took has to leave the open side and appear on the "
        "other, which is the one thing a single-event summary cannot show"
    )
    assert proposal_id not in {item["proposal_id"] for item in still_open["items"]}
    assert (open_proposal["execution_id"], open_proposal["step_id"]) == (None, None)
    assert open_proposal["actor_id"], (
        "a proposal records who advised, and nothing in the request says who "
        "that is, so a dropped principal is only visible on a read"
    )
    assert (advised["execution_id"], advised["step_id"]) == (held_execution, produced_by), (
        "taking a proposal is the join this context exists for, and the read "
        "is where a caller sees that anything came of its advice"
    )
    assert [item["device_id"] for item in resolved["items"]] == [device_id], (
        "resolving an address to an id is the first call any adapter makes, "
        "because ids are minted here and a reporter holds only the address"
    )
    assert (while_faulted, after_recovery, after_retirement) == (
        "Faulted",
        "Available",
        "Retired",
    ), (
        "each transition tool must reach its own status; two matching means "
        "two bundle fields are wired to one handler, and recovery returning "
        "to Available is the one edge on this machine that points backwards"
    )
    assert [item["dataset_id"] for item in produced["items"]] == [dataset_id]
    assert held == {
        "dataset_id": dataset_id,
        "execution_id": held_execution,
        "step_id": produced_by,
        "external_ref_scheme": "tiled-node-path",
        "external_ref_value": "raw/uid-completing",
    }


def _tools_a_walk_calls() -> frozenset[str]:
    """Tool names passed to `_call` inside a test in this file.

    Parsed rather than grepped. The first version searched the source
    text after the marker `def _call`, which this function also
    contains, so it split on its own body and found nothing. A file that
    reads itself has to be read as code, or the reader keeps matching
    the reader.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for test in tree.body:
        if not isinstance(test, ast.FunctionDef) or not test.name.startswith("test_"):
            continue
        for node in ast.walk(test):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_call"
            ):
                names |= {
                    argument.value
                    for argument in node.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                }
    return frozenset(names)


def test_the_call_scan_finds_the_walks_it_ranges_over() -> None:
    """Guard the parse: finding nothing would report every tool as missing.

    That is the louder of the two failures, so it would be noticed. This
    exists for the quieter one, where a change to `_call` leaves the
    scan finding some calls and silently skipping others.
    """
    found = _tools_a_walk_calls()
    assert len(found) >= 4, f"only {len(found)} tool calls found across every execution: {found}"


def test_every_published_tool_is_executed_by_a_walk_in_this_file() -> None:
    """The bar this file sets, checked rather than trusted.

    A tool added to `TOOLS_A_CLIENT_SHOULD_SEE` without a call added to
    an execution leaves a body nothing runs, and the listing test above goes
    green on it. The two sides are the pinned set and the calls actually
    written, which are different acts in different parts of the file.
    """
    missing = TOOLS_A_CLIENT_SHOULD_SEE - _tools_a_walk_calls()
    assert not missing, (
        f"Published tools no execution in this file calls: {sorted(missing)}. Listing a "
        "tool proves the mount; only calling it runs the body, which is a second "
        "copy of what the route does. Add it to an existing execution rather than a "
        "test of its own, because each test here boots the application."
    )
