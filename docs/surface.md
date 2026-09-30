# The surface

Every operation this system has, in one list.

Each one is published twice, as an HTTP route and as an MCP tool, out of a
single piece of code. A person and a machine reach the same model through the
same rules, which is what makes granting a machine less than a person mean
anything.

**This page is generated.** `make docs-surface` rewrites it from the code, and a
test regenerates it on every run and fails on any difference, so it cannot be
out of date. Do not edit it by hand. What each operation means, and what it
refuses, is on that context's own page.

49 operations, across 7 bounded contexts.

## Access

[What this context is for](bounded-contexts/access.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `POST /actors` | `register_actor` | `201` |
| `GET /actors/{actor_id}` | `get_actor` | `200` |
| `POST /actors/{actor_id}/deactivate` | `deactivate_actor` | `204` |
| `POST /actors/{actor_id}/reactivate` | `reactivate_actor` | `204` |

## Authority

[What this context is for](bounded-contexts/authority.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `POST /policies` | `define_policy` | `201` |
| `GET /policies/{policy_id}` | `get_policy` | `200` |
| `POST /policies/{policy_id}/permissions` | `grant_permission` | `204` |
| `DELETE /policies/{policy_id}/permissions/{principal_id}/{command_name}` | `revoke_permission` | `204` |

## Counsel

[What this context is for](bounded-contexts/counsel.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `GET /inquiries` | `list_inquiries` | `200` |
| `POST /inquiries` | `make_inquiry` | `201` |
| `GET /inquiries/{inquiry_id}` | `get_inquiry` | `200` |
| `POST /inquiries/{inquiry_id}/answer` | `answer_inquiry` | `204` |
| `POST /inquiries/{inquiry_id}/claim` | `claim_inquiry` | `204` |
| `GET /proposals` | `list_proposals` | `200` |
| `POST /proposals` | `make_proposal` | `201` |
| `GET /proposals/{proposal_id}` | `get_proposal` | `200` |
| `POST /proposals/{proposal_id}/adopt` | `adopt_proposal` | `201` |
| `POST /proposals/{proposal_id}/take` | `take_proposal` | `204` |

## Custody

[What this context is for](bounded-contexts/custody.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `GET /datasets` | `list_datasets` | `200` |
| `POST /datasets` | `register_dataset` | `201` |
| `GET /datasets/{dataset_id}` | `get_dataset` | `200` |

## Equipment

[What this context is for](bounded-contexts/equipment.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `GET /devices` | `list_devices` | `200` |
| `POST /devices` | `register_device` | `201` |
| `GET /devices/{device_id}` | `get_device` | `200` |
| `POST /devices/{device_id}/fault` | `fault_device` | `204` |
| `POST /devices/{device_id}/recover` | `recover_device` | `204` |
| `POST /devices/{device_id}/retire` | `retire_device` | `204` |

## Execution

[What this context is for](bounded-contexts/execution.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `GET /executions` | `list_executions` | `200` |
| `POST /executions` | `dispatch_execution` | `201` |
| `GET /executions/{execution_id}` | `get_execution` | `200` |
| `POST /executions/{execution_id}/claim` | `claim_execution` | `204` |
| `POST /executions/{execution_id}/end` | `end_execution` | `204` |
| `POST /executions/{execution_id}/steps` | `report_step` | `204` |
| `POST /executions/{execution_id}/steps/{step_id}/run` | `report_step_run` | `204` |
| `GET /operations` | `list_operations` | `200` |
| `POST /operations` | `define_operation` | `201` |
| `GET /operations/{operation_id}` | `get_operation` | `200` |
| `GET /procedures` | `list_procedures` | `200` |
| `POST /procedures` | `define_procedure` | `201` |
| `GET /procedures/{procedure_id}` | `get_procedure` | `200` |
| `GET /steps/without-datasets` | `list_steps_without_datasets` | `200` |

## Pursuit

[What this context is for](bounded-contexts/pursuit.md)

| HTTP | MCP tool | On success |
| --- | --- | --- |
| `GET /pursuits` | `list_pursuits` | `200` |
| `POST /pursuits` | `start_pursuit` | `201` |
| `GET /pursuits/{pursuit_id}` | `get_pursuit` | `200` |
| `POST /pursuits/{pursuit_id}/charges` | `charge_pursuit` | `201` |
| `POST /pursuits/{pursuit_id}/resume` | `resume_pursuit` | `204` |
| `POST /pursuits/{pursuit_id}/rounds` | `open_pursuit_round` | `201` |
| `POST /pursuits/{pursuit_id}/rounds/{round_index}/close` | `close_pursuit_round` | `200` |
| `POST /pursuits/{pursuit_id}/withdraw` | `withdraw_pursuit` | `204` |
