# Authority

Authority is the bounded context that answers one question: who may issue which command?

It holds one aggregate, the Policy, and four things you can do to it. Every command and query anywhere in the keeper passes through the answer before anything else happens, so this is the one context whose output the other six depend on without knowing it exists.

It is one of two contexts whose subject is a permission rather than a thing. The other is [Pursuit](pursuit.md), and the two answer different questions. Authority is the standing rulebook: general, about the system, and true until somebody changes it. A pursuit is one person's authorization of one goal: bounded, revocable, and about a stretch of time. The rulebook says an agent may adopt suggestions at all; a pursuit is why one particular adoption is allowed to happen with nobody watching.

## What a Policy is

A policy is the rulebook one deployment authorizes against: the set of pairs that are permitted. Everything not in the set is refused, so a policy says what may happen rather than what may not.

```
   Policy
     id           a UUID minted when the policy is authored
     permissions  a set of permissions, and nothing else

   Permission
     principal_id  who may act
     command_name  the one command they may issue
```

A deployment authorizes against exactly one policy, named by the `AUTHZ_POLICY_ID` setting. Switching rulebooks means pointing at a different id and restarting.

## Why a pair, and not two lists

This is the shape the whole context turns on, and the wrong shape is the obvious one.

An earlier version in the codebase this chassis came from held two independent sets, the permitted principals and the permitted commands, and checked membership in each separately. That grants every principal every command. A rulebook listing a read-only status feed alongside a supervisor who may abort a run had, between those two lines, granted the feed permission to abort runs. Nothing ever exercised it, and the rulebook still claimed more than the system it governed did, which is the one thing a rulebook must never do.

Holding pairs makes that cross product unrepresentable rather than merely unchecked. There is no test for it, because there is no way to write the bug.

## Why it has no name

The same reasoning as the Actor's, in [Access](access.md#why-it-has-no-name). One deployment authorizes against one policy, selected by id in settings, so a name would be decoration on a singleton, and a field added before a caller asks for it is shaped by guesswork about who will read it.

## The rule a policy carries about itself

A rulebook says who may edit the rulebook, which makes it the only thing standing between a deployment and a state nobody can repair. Revoke the last principal permitted to grant, and nobody can ever add anyone again short of restarting the process with authorization switched off.

So every policy must permit at least one principal to issue each of its governing commands, and today that set has one member:

```
   GrantPolicyPermission     governing
   RevokePolicyPermission    not governing
   GetPolicy                 not governing
```

The asymmetry is the interesting part, and it is not an oversight.

**Revoking does not govern.** A policy nobody may revoke under can only grow, and whoever may grant can always grant the revoke permission back, so that loss is recoverable through the API. A policy nobody may grant under can only shrink, and shrinking never restores anything, so that loss is not. Only the irrecoverable power belongs in the set. Requiring a revoker as well would make every bootstrap carry a permission it could mint for itself.

**Reading does not govern.** Losing the ability to read a policy is uncomfortable and not unrecoverable: whoever may grant can grant the read back, and until they do the policy can still be changed blind.

The check runs against the permissions a policy is about to hold, not the ones it holds now. Defining passes the set being written, so a policy is born changeable or is not born at all. Revoking passes what would be left after the removal, so the last one is refused rather than reported on afterwards. Granting skips the check entirely, because adding can never take a power away.

The governing names live on the aggregate rather than in the slice that issues them, and `tests/architecture/test_governing_commands_exist.py` compares them against the command names handlers actually declare. A governing name no handler issues would guard a command nobody can send, and a policy could then be accepted as governable while being a brick.

## The operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Author a policy | `POST /policies` | `define_policy` | `201` with the new id |
| Add one permission | `POST /policies/{policy_id}/permissions` | `grant_permission` | `204` |
| Remove one permission | `DELETE /policies/{policy_id}/permissions/{principal_id}/{command_name}` | `revoke_permission` | `204` |
| Read the rulebook | `GET /policies/{policy_id}` | `get_policy` | `200` with the permissions |

Every operation is published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes above are declared once, in `src/keeper/authority/routes.py`.

Reading is authorized like everything else, and it is worth more here than on most reads: a rulebook is a map of everything the system will accept, so a caller who can read one learns where to aim without being permitted anything by it.

## Deciding one command

Two conditions, both required, and deny by default on each.

```
   permitted   the configured policy holds this exact pair
   standing    Access has an actor under that principal id, and it is active
```

Policy is checked first. A caller the rulebook does not name is refused without Access being read at all, which keeps the denial path to one fold and means a caller who was granted nothing learns nothing about whether this system has a record of them.

**Standing is checked here rather than at the front door**, because authentication never consults Access. It establishes who is calling, from a token or a proxy-set header, and an actor being switched off is not a fact about that. Without this second condition, deactivating an actor would take nothing away: their grants would keep working, and the only way to stop them would be to revoke every permission they hold one at a time.

**Authority reads Access and never writes to it.** Deactivating an actor leaves every permission they hold sitting in the policy, inert; reactivating makes them effective again with nothing re-granted. Cascading a deactivation into revocations would let Access quietly rewrite Authority's rulebook, and would turn a reversible switch into an act nobody can undo without knowing what was there before.

Both aggregates are folded from their streams on every call, and there is no cache. They are a handful of rows each, and a cache is not a line of code but an invalidation story: a grant the next request does not see is the bug it would have to be designed against.

## What a permission does not check

Both halves of a permission are stored as bare values with nothing verified behind them. `principal_id` is not looked up in Access at write time, and `command_name` is not compared against the commands this build actually has. So a typo produces a permission that silently never matches, rather than a refusal when it is written.

That is deliberate, and it is written down here because it is the invariant a reader assumes exists. The operational answer is the log: every denial records the principal and the command it refused, so a permission naming a command nobody issues never appears there, and the command the caller actually sent does. That pair of facts identifies the typo.

Checking at write time would need the aggregate to know every command this build has, which is a list that lives in the handlers and changes with each slice.

## The system principal

The system principal is the identity an unauthenticated request runs as under the development posture. It exists so a deployment with no rulebook yet can still be operated, which is how the first policy gets written at all.

It is refused as a grantee and never as an author. The party that defines the first policy is the system principal, recorded in the event envelope as having done so, and it grants that policy to real registered actors. Those are two different fields, and the whole bootstrap rests on their being different.

What the refusal prevents is the shortcut afterwards: granting the shared fallback identity a standing power, so that anything reaching the fallback inherits it and no audit trail says who acted. A background job that needs authority gets a registered actor of its own.

It also makes the cutover one-way through the API. Under the permissive adapter an unauthenticated request is permitted everything; under the real one it is permitted nothing, because the system principal cannot hold a permission and so can never match. A deployment authors its first policy permissively, points `AUTHZ_POLICY_ID` at it, and restarts. It cannot author one afterwards. [Runtime](../reference/runtime.md#production-hardening) gives the bootstrap in the order it has to happen, and the two ways of getting it wrong.

## What the stream holds

There is no policies table. A policy's current state is recomputed by replaying its events every time it is read, which happens on every authorized request.

```
   PolicyDefined              policy_id, permissions, occurred_at
   PolicyPermissionGranted    policy_id, permission, occurred_at
   PolicyPermissionRevoked    policy_id, permission, occurred_at
```

The two change events carry the single pair that moved, never the resulting set. Writing the whole set on every change would make each row a snapshot, and two operators granting different permissions would overwrite each other instead of both landing. It also answers the question a rulebook is most often asked, which is who lost what and when; a snapshot of the survivors answers that only by diffing two rows.

A permission set is stored as a sorted list of pairs. A set has no order, so an unsorted dump would give the same policy a different payload on different runs, and a stored row has to be reproducible from the state that produced it. The same ordering serves both read surfaces, so a client polling a policy cannot see the rulebook shuffle between calls and mistake that for a change.

`PolicyPermissionRevoked` carries no reason. What a revocation was for is a fact about a decision rather than about the policy, and a free-text field is the shape that cannot be queried, cannot be validated, and ends up holding somebody's name in the one table that cannot be edited afterwards. If the need appears it arrives as a closed set of values, never as prose. That ban is enforced across every context by `tests/architecture/test_events_carry_no_personal_data.py`.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `UnauthorizedError` | 403 | The caller is known and not allowed. Distinct from 401, where we do not know who is asking. |
| `PolicyNotFoundError` | 404 | The id names no policy. |
| `PolicyAlreadyExistsError` | 409 | Definition was aimed at an id that already has a history. |
| `PolicyCannotGrantPermissionError` | 409 | The permission is already held. |
| `PolicyCannotRevokePermissionError` | 409 | The permission is not held. |
| `PolicyWouldBeUngovernableError` | 422 | The policy would be left with nobody able to change it. |
| `SystemPrincipalCannotBeGrantedError` | 422 | The grantee is the unauthenticated fallback identity. |
| `ConcurrencyError` | 409 | The policy changed between the read and the write. Reload and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body, so no cached answer can be right. |

The two 422s are refusals of the shape being asked for rather than conflicts with what is stored: the same request would be refused against an empty system. That is what separates them from the 409s.

A repeated grant and a repeated revoke are both refused rather than absorbed. A set absorbs a duplicate member silently and a set difference absorbs a missing one, so two operators each acting on what they believe to be a new permission would both be told they succeeded. One of them is reading a stale rulebook and needs to know.

## Retrying safely

Defining a policy accepts an `Idempotency-Key`. Send the same key twice and the second call returns the first call's answer instead of authoring a second rulebook, which matters more here than elsewhere: a deployment authorizes against whichever id somebody wrote down.

Granting and revoking do not take one. A replayed one of either is already refused by the domain, so a retry key would buy a friendlier status code rather than prevent a second write. Reading does not take one because there is nothing to replay.

## Where the code is

```
   src/keeper/authority/
     aggregates/policy/      state, events, the fold, and how to load one
     adapters/
       policy_authorize.py   the real Authorize port: policy, then standing
     features/
       define_policy/        one directory per operation
       grant_permission/
       revoke_permission/
       get_policy/           a query slice, so no decider: reading decides nothing
     routes.py               HTTP mounting and the error-to-status mapping
     tools.py                MCP tool registration
     wire.py                 which handler gets idempotency, which gets tracing
```

The adapter is what makes this context unlike the other six. Theirs hold summary lookups serving their own queries; this one implements a port that every handler in the system calls before it decides anything, Authority's own four included. So the dependency runs the other way from the usual: Authority reads Access at decision time, and the other six know only that an `Authorize` port exists.

## What is not here yet

**A policy cannot say where a command came from.** The port takes a surface id and the adapter accepts it and ignores it, because no aggregate models a surface. So a policy cannot yet express "this principal, this command, but only over HTTP". Taking the argument and doing nothing with it is what lets that arrive as a change to one adapter rather than to every call site.

**A denial carries prose rather than a code.** Two conditions means two reasons, and a machine-readable discriminator saying which one failed would have no reader today: every denial is a 403, the surfaces do not branch on it, and what an operator counts is in the log, where the two failures are separate events. The trigger for adding one is the first caller that has to behave differently depending on why it was refused.

**There are no roles and no groups.** Every permission names one principal and one command, so granting the same twelve commands to five service accounts is sixty grants. Nothing has asked for the shorthand yet, and a role is a second thing that can go stale against the commands this build has.

**Policies cannot be listed.** Only fetched by id, which is all a deployment needs when it authorizes against one.
