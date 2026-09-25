# Patterns

*Read side, query slices, projections, idempotency, cross-aggregate validation, cross-stream uniqueness, rejections.*

The shapes that recur across slices: how reads work, when retries stay safe, where slices need another aggregate, what failure looks like. New slices follow them or have a reason not to.

## Read side

Two read paths, picked by query shape.

- **Fold-on-read** (`aggregates/<aggregate>/read.py:load_<aggregate>`) for single-aggregate `GET`. Cost is O(events per stream).
- **Projection worker** for list, filter, search, and high-traffic queries. A background task tails the events channel; `GET` reads a denormalized table.

Read repositories live with the aggregate, not the slice; they operate on the stream regardless of which command produced the events.

## Query slices

Symmetric with command slices. No decider, no events.

**`get_<aggregate>`**: single-resource read by id.

```
features/get_<aggregate>/
├── query.py        # GetThing(thing_id: UUID)
├── handler.py      # bind(deps) -> Handler returning Thing | None
├── route.py        # GET /<resource>/{id} -> 200 + DTO  (404 on None)
└── tool.py         # MCP tool
```

Reads via fold-on-read. Returns domain types; route and tool do their own Pydantic DTO mapping.

**`list_<aggregates>`**: keyset-paginated page of many.

**The verb says how many, not where from.** `get_` returns one thing and `list_` returns a page, and that is the whole of the distinction. Reading `list_` as "projection-backed" is the tempting mistake: every list slice does read `proj_*` in a deployment with a database, but the same slice folds every stream in one without, and which happens is decided in `wire_<bc>` rather than by the name. A verb that promised a backing store would be false in the environment the unit and contract tiers run in, and would have to change if a `get_` ever outgrew its fold.

Reads `proj_<bc>_<name>` through a read port the BC declares, not through `deps.pool` directly. The cursor is an opaque base64 of `(created_at, UUID)` via `encode_cursor` / `decode_cursor`. Default page 50, max 100. Empty: `200 {"items": [], "next_cursor": null}`. Malformed cursor: 422 via `InvalidCursorError`.

**The port is not optional, and the test suite is what says so.** This application is meant to boot and answer with no database, which is what the unit and contract tiers run against, and the MCP surface contract requires every published tool to be called successfully in a walk. A list handler reading `deps.pool` refuses in that environment; one that returns an empty page while rows exist is worse. So a list slice takes `bind(deps, <port>)`, the port is declared with the aggregate beside its `read.py`, and `wire_<bc>` picks the implementation by whether there is a pool. The in-memory one folds every stream, which is what the table exists to avoid and is free when the store is a dictionary. A shared contract suite under `tests/_port_contracts/` is run against both, because the two share no code.

Query handlers DO call `kernel.authz.authorize(...)` with the query name as `command_name`. Per-row scoping needs ReBAC and is deferred. The port method is `authorize(principal_id, command_name, surface_id)`; the kernel attribute is `authz`, which is shorter and less collision-prone than `authorize`.

## Projections

Background workers maintain denormalized read tables by tailing the event store. The machinery lives at `keeper.infrastructure.projection`; the composition root spawns one in-process worker via the FastAPI lifespan, which advances every registered `Projection` along the event stream.

- **`Projection` Protocol** in `keeper/<bc>/projections/<name>.py`: `name` (matches the `proj_*` table and the bookmark), `subscribed_event_types`, `apply(event, conn)`. Advance orders by `(transaction_id, position)` with `pg_snapshot_xmin` exclusion.
- **`apply()` MUST be idempotent**, because delivery is at-least-once. Use `INSERT ... ON CONFLICT (key) DO NOTHING/UPDATE`, or justify with `# idempotent: <reason>`. Enforced by `test_projection_apply_is_idempotent.py`, which reads the SQL constants rather than the behaviour: it can tell whether a statement says what a repeat does, not whether it is true. The behaviour is asserted by rewinding a bookmark and replaying a real batch, in the integration tier.
- **Per-BC registration**: each BC exports `register_<bc>_projections(registry, deps)` from `projections/register.py`; the composition root calls it after `wire_<bc>(deps)`. See [Layout](layout.md#the-projection-registrar) for why the registrar lives in the package rather than in a flat module.
- **Migration shape**: every `proj_*` migration includes `GRANT SELECT, INSERT, UPDATE, DELETE TO keeper_app` plus `INSERT INTO projection_bookmarks (name) VALUES (...) ON CONFLICT DO NOTHING`. `test_projections_have_a_table_and_a_bookmark.py` checks that every registered projection has both, because a projection missing either one fails inside the worker's backoff loop while every write succeeds. It does NOT check the grant: `test_migration_grants.py` ranges over append-only tables only, and a `proj_*` table is the opposite kind.

Tests use `await drain_projections(pool, registry, deadline_seconds=2.0)` instead of `asyncio.sleep`, or drive `advance_subscriber_once` directly when they want to control exactly how far the projection has got.

**Settings:**

- `projection_use_listen_notify: bool = True`: NOTIFY wake-up, tens of milliseconds. Flip to False if the commit lock contends.
- `projection_poll_interval_seconds: float = 5.0`: safety-net poll. Floor 0.1s.

## Lifecycle timestamps

Wall-clock timestamps on aggregates (`created_at`, `versioned_at`, `deprecated_at`) belong on the **projection**, not on aggregate state.

- **State stays narrow.** Timestamps do not gate invariants, so a decider should not carry them. Removing the field shrinks the `from_stored` and payload surface.
- **The projection derives them from the envelope's `occurred_at`.** Each genesis event sets `created_at`; subsequent transition events update the matching `<verb>_at` column. Apply stays idempotent.
- **Contract tests source timestamps from the projection row**, not from the aggregate.
- **Single-record reads still fold the stream.** When a route needs a timestamp without joining the projection, derive it from the envelope's `occurred_at` at fold time rather than carrying it in state.

## Idempotency

Create-style commands accept an idempotency key so client-side retries do not duplicate. The standard is the IETF [`Idempotency-Key`](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header-07) header. The decorator lives at `keeper/infrastructure/idempotency.py`; the wrap is applied in each BC's `wire.py`.

- **Apply** to create-style commands, where the server generates an id and a retry would otherwise duplicate.
- **Skip** for queries, and for updates that do not need cached-success-on-retry.

```python
register_thing=with_idempotency(
    register_thing.bind(deps),
    deps.idempotency_store,
    command_name="RegisterThing",
    serialize_result=str,
    deserialize_result=UUID,
)
```

A slice exposes `Handler` (bare) and `IdempotentHandler` (wrapped, optional `idempotency_key`). Tests use the bare one; production wires the wrapped one. Routes extract via `Header(alias="Idempotency-Key")`.

The cache namespace is the composite `(principal_id, key, surface_id)` per IETF draft-07 section 5, so the same `Idempotency-Key` cannot collide across the HTTP and MCP surfaces. `command_hash` and `command_name` are conflict-detection parameters on `claim()`, not part of the namespace tuple.

`IdempotencyConflictError` (same key, different body) returns 422. Key max 255 chars. MCP tools pass `idempotency_key=None`, since MCP has no standard for it yet.

## Cross-aggregate validation

Some commands validate against another aggregate's state.

**The handler loads upstream aggregates into a slice-local context dataclass; the pure decider takes the context as an opaque parameter.**

```python
# slice/context.py
@dataclass(frozen=True)
class ThingBindingContext:
    template: Template
    parts: dict[UUID, Part]


# slice/handler.py
template = await load_template(deps.event_store, command.template_id)
if template is None:
    raise TemplateNotFoundError(command.template_id)

parts: dict[UUID, Part] = {}
for part_id in sorted(command.part_ids, key=str):
    part = await load_part(deps.event_store, part_id)
    if part is None:
        raise PartNotFoundError(part_id)
    parts[part_id] = part

context = ThingBindingContext(template=template, parts=parts)
events = decide(state=None, command=command, context=context, now=now, new_id=new_id)


# slice/decider.py
def decide(
    state: Thing | None,
    command: DefineThing,
    *,
    context: ThingBindingContext,
    now: datetime,
    new_id: UUID,
) -> list[ThingDefined]:
    if context.template.status is TemplateStatus.DEPRECATED:
        raise ThingBoundTemplateDeprecatedError(context.template.id)
```

- **The decider stays pure.** No `await`, no port injection. Tests build contexts directly.
- **Capture, do not recompute.** Bind-time data is captured in the event payload; replay never re-loads it.
- **Eventual consistency.** Concurrent upstream changes between handler-load and event-append are accepted.
- **Existence versus state.** The handler raises `<X>NotFoundError` (404); the decider raises domain errors (409).
- **Slice-local context.** Each cross-validating slice gets its own `<slice>/context.py`. Promote to a shared form only after the rule of three.

This is the canonical Functional Core / Imperative Shell shape: data not in the stream is fetched in the shell and passed to the pure core as plain values.

### Dispatch-slice exception

Most command slices have a decider returning `list[<Event>]` for events on the slice's own aggregate. A small set of cross-BC slices instead validate a loaded aggregate from another BC and dispatch to that BC's own slice without writing an event on any aggregate the consuming BC owns.

Treat `decider.py` in such slices as a pure validator-and-extractor: the canonical-args check still applies, the return-type expectation does not. The slice's docstring must explain the dispatch shape, and the function's `Invariants:` block enumerates rejections the same way a true decider does. Adopt this shape only when the slice genuinely owns no aggregate writes; when in doubt, emit an event on the source aggregate's stream and dispatch via `EventStore.append_streams`.

## Cross-stream uniqueness

Some aggregates carry a natural key that must be unique across every stream of their kind. No single aggregate stream can enforce that on its own; event-sourced aggregates have no consistency boundary spanning siblings. Two patterns close the gap. Pick by whether a duplicate should fail the caller synchronously or be tolerated as a swallowed audit row.

**Variant A: stream-derivation.** The stream id is derived from the natural key, `stream_id = uuid5(<frozen namespace>, <natural key>)`, so a duplicate-key genesis targets the same stream and collides on `append_streams(expected_version=0)`. The handler surfaces that as `<X>AlreadyExistsError` (409) on the request path. A read-side unique index is optional defence in depth here, not the guard. Derivers live next to the aggregate, at `aggregates/<aggregate>/_stream_id.py`.

**Variant B: projection unique index.** The aggregate gets a fresh `IdGenerator` id, and a partial `UNIQUE INDEX` on the `proj_<bc>_*` table is the only cross-stream guard. A duplicate command still appends an event, to a different stream; the projection writer catches the `UniqueViolation`, logs a warning, and keeps advancing, so the request path still returns success.

**Variant B has a cost that is easy to miss: the swallowed row is invisible.** The projection drops it, so a run that exists in the log is missing from every listing, and a list endpoint over that table undercounts. Execution declined the index on its run summary for exactly this reason, and the decision turns on the query shape: a lookup that must return one answer needs the index, and a list that can return two does not. Prefer showing the caller the duplicate over hiding it, unless something downstream genuinely cannot cope with two.

Decision rule:

- **Pick A** when the caller should get a synchronous 409 on a duplicate and the natural key is immutable and stable across deployments.
- **Pick B** when a duplicate is tolerable as a swallowed audit row and re-registration after a tombstone must stay possible. The uniqueness is then conditional: the index carries a partial `WHERE` excluding the terminal state, so a new row can take the key once the prior one is retired.

Two rules hold wherever the pattern is used:

- **The namespace is frozen (Variant A).** The uuid5 namespace UUID is a permanent constant. Changing it re-keys every stream, breaking idempotent genesis and cross-deployment determinism. Mark it MUST NOT CHANGE at the definition site.
- **The derivation key must byte-match the read-side expression.** When both layers exist, the value hashed into the stream id must equal the value the index keys on. If one lower-cases, the other must too.

A name-derived stream id interacts with any bootstrap seed that writes the same stream: seeding and deriving from the same name will collide. Run the whole contract suite after any change to a seed or a derivation namespace.

This is the deliberate deviation from the default in [conventions.md](conventions.md#identifiers). Reach for it only when a natural key, not a surrogate id, owns identity.

## Rejections

A slice's behavioral contract has two halves: the events the decider emits on success, and the named exceptions it raises on failure. Both are first-class. When designing a new slice, enumerate the rejection list as a peer to the event list, not as an afterthought.

| Family | Naming | HTTP | Defined in |
| --- | --- | --- | --- |
| Validation | `Invalid<Aggregate><Field>Error(ValueError)` | 400 | `aggregates/<aggregate>/state.py` |
| Not found | `<Aggregate>NotFoundError` | 404 | `aggregates/<aggregate>/state.py` |
| Already exists | `<Aggregate>AlreadyExistsError` | 409 | `aggregates/<aggregate>/state.py` |
| State transition | `<Aggregate>Cannot<Verb>Error` | 409 | `aggregates/<aggregate>/state.py` |
| Authorization | `UnauthorizedError` | 403 | `keeper/<bc>/errors.py` |
| Idempotency conflict | `IdempotencyConflictError` | 422 | `keeper/infrastructure/ports/` |
| Cursor parse | `InvalidCursorError` | 422 | `keeper/infrastructure/projection/` |

Existence versus state, per the rule above: the handler raises `<X>NotFoundError` (404) when an upstream aggregate is missing entirely; the decider raises `<X>Cannot<Verb>Error` (409) when state forbids the transition.

**Decider docstrings carry an `Invariants:` block** listing each rejection inline with its exception name. This is the contract; a test author or API consumer should not have to re-derive it from the body.

```python
def decide(state: Thing | None, command: AddThingPart, *, now: datetime) -> list[ThingPartAdded]:
    """Decide the events produced by adding a part to an existing Thing.

    Invariants:
      - State must not be None (thing must exist) -> ThingNotFoundError
      - Thing must not be Retired (lifecycle gate) -> ThingCannotAddPartError
      - Part name must not already exist (strict, not idempotent) -> ThingCannotAddPartError
    """
```

**Central exception-to-status mapping** lives in each BC's `routes.py`. One handler per family, registered against a tuple of error classes via a loop. Adding a new error in a family is one tuple entry, not a new handler.

```python
for cannot_transition_cls in (ThingCannotActivateError, ThingCannotRetireError):
    app.add_exception_handler(cannot_transition_cls, _handle_cannot_transition)
```

Routes do NOT wrap handler calls in try/except. The decider raises, the central handler catches, FastAPI emits the JSON response. The response body is uniform: `{"detail": str(exc)}`.

**Cross-BC infra errors** (`ConcurrencyError`, `IdempotencyConflictError`, `IdempotencyClaimLostError`, `CachedHandlerError`, `InvalidCursorError`) are registered globally by the first-booted BC. Other BCs do NOT re-register them; the JSON shape is the same regardless of which BC issued the error.

**Cross-BC domain errors** (BC X's slice raises BC Y's domain error via a cross-aggregate `load_*` call) are registered ONLY by the owning BC. FastAPI's `add_exception_handler` is app-scoped and last-wins, and the fitness test that requires a handler only walks each BC's own `aggregates.*.__all__`, so a duplicate registration in the consumer BC is neither required nor useful. Document the non-registration with a comment near the consumer's existing handler-tuple loops.

**Boundary 422s via Pydantic** are NOT raised as domain errors. Required-field length, pattern, and type checks live in the route's request model and surface as FastAPI's standard 422. When enumerating a slice's rejections at design time, list these as boundary cases so the rejection list is exhaustive.
