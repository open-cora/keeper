# Access

Access is the bounded context that answers one question: who is this?

It holds one aggregate, the Actor, and four operations on it. Nothing else in the keeper knows who anybody is, so anything that needs to record who did something asks Access for an actor id and stores that.

## What an Actor is

An actor is a party this system has a record of: a person, a service account, or a background process. The record is deliberately small.

```
   Actor
     id      a UUID minted at registration, never reused
     active  whether the actor is switched on
```

That is the whole of it. Two fields.

## Why it has no name

A display name is the first field a reader expects here, and its absence is a decision rather than an oversight. Three reasons, in order of how much they matter.

**The names are not ours to hold.** The actors this system sees are service accounts, and a service account is named where it is provisioned. A name field here would be a copy that goes stale, shaped today by guesswork about who will read it and argued with tomorrow by the first caller who actually needs one.

**An event cannot be edited.** Events are append-only, enforced at the database role level rather than by convention: the application's role has no UPDATE, DELETE or TRUNCATE grant on the events table. So a name written into a payload cannot later be taken back out. A field that can only ever be added to is a bad place to learn what you want.

**It keeps personal data out while the question stays open.** Nothing in the keeper holds personal data today. Writing no name is the cheapest way to keep that true, and it costs nothing to add a name later, in a considered place, once something real needs one.

This is enforced, not just intended. `tests/architecture/test_events_carry_no_personal_data.py` reads every event class and every payload builder across every bounded context and refuses a field whose name looks like personal data.

## The four operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Register a new actor | `POST /actors` | `register_actor` | `201` with the new id |
| Switch one off | `POST /actors/{actor_id}/deactivate` | `deactivate_actor` | `204` |
| Switch one back on | `POST /actors/{actor_id}/reactivate` | `reactivate_actor` | `204` |
| Read one back | `GET /actors/{actor_id}` | `get_actor` | `200` with the actor |

Every operation is published twice, once as an HTTP route and once as an MCP tool, from the same handler. The handler knows nothing about either surface; the status codes above are declared once, in `apps/keeper/src/keeper/access/routes.py`.

Registering takes no fields at all. The caller controls nothing about the new actor: the id, the timestamp and the correlation id all come from the handler, so the decision can be replayed later and produce the same events.

## The switch

```
                 register
                    |
                    v
          +--------------------+
          |       active       |
          +--------------------+
             |              ^
  deactivate |              | reactivate
             v              |
          +--------------------+
          |      inactive      |
          +--------------------+

   deactivating an inactive actor   refused, 409
   reactivating an active actor     refused, 409
```

A repeat call is refused rather than quietly succeeding. Two operators each deactivating what they believe to be a live actor should not both be told it worked; one of them is looking at a stale view and needs to know.

## What the stream holds

There is no actors table. An actor's current state is recomputed by replaying its events every time it is read.

```
   ActorRegistered     actor_id, occurred_at
   ActorDeactivated    actor_id, occurred_at
   ActorReactivated    actor_id, occurred_at
```

Three events, each carrying an id and a time and nothing else.

Reactivation is its own event rather than a flag being set back. That is what makes the history readable: how many times an actor went off and on, and when, exists only because each switch left its own row. A boolean that got flipped twice remembers nothing.

`ActorDeactivated` carries no reason, for the same reason there is no name. A free-text reason field is the field most likely to end up holding something about a person, in the one table that cannot be edited afterwards.

Replaying a whole stream to read one actor is the right trade here, because a stream is a handful of rows. It is the wrong trade for listing or filtering actors, which cannot replay everybody. A query of that shape needs a maintained summary table and belongs in its own module.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `UnauthorizedError` | 403 | The caller is known and not allowed. Distinct from 401, where we do not know who is asking. |
| `ActorNotFoundError` | 404 | The id names no actor. Different from an inactive one, which exists. |
| `ActorAlreadyExistsError` | 409 | Registration was aimed at an id that already has a history. |
| `ActorCannotBeDeactivatedError` | 409 | Already off. |
| `ActorCannotBeReactivatedError` | 409 | Already on. |
| `ConcurrencyError` | 409 | The actor changed between the read and the write. Reload and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body, so no cached answer can be right. |

Five different things share 409. They stay separate classes because the caller's next move differs: retry, stop, or re-read.

## Retrying safely

Registering accepts an `Idempotency-Key`. Send the same key twice and the second call returns the first call's answer instead of creating a second actor.

The two switch operations do not take one, deliberately. A replayed deactivation is already refused by the domain, so a retry key would only buy a friendlier status code, not prevent a second write. Reads do not take one because there is nothing to make idempotent.

## Where the code is

```
   apps/keeper/src/keeper/access/
     aggregates/actor/       state, events, the fold, and how to load one
     features/
       register_actor/       one directory per operation, six modules each
       deactivate_actor/
       reactivate_actor/
       get_actor/            a query slice, so no decider: reading decides nothing
     routes.py               HTTP mounting and the error-to-status mapping
     tools.py                MCP tool registration
     wire.py                 which handler gets idempotency, which gets tracing
```

Each write operation is a vertical slice: its own command, its own decision function, its own handler, its own route and tool. Slices do not import each other. Adding a fifth operation means adding a directory, not editing four existing ones.

## What is not here yet

Access has no notion of roles, permissions, or groups. Authorization is a port every handler calls before deciding anything, but the only implementation today permits every command. That is a development default rather than a production posture: booting the production tier without a real one is refused outright, instead of being allowed to fall back to the permissive one.

Actors also cannot be listed or searched, only fetched by id. None of this is designed yet, and none of it should be until something asks for it.
