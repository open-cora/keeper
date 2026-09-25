# Modeling

*Event sourcing, value objects, field grouping.*

Events are immutable; everything else evolves. The rules below exist to keep that asymmetry honest: schema evolution that does not lie about old events, value objects that re-validate on read, primitives at the wire and value objects at the boundaries.

## Event sourcing

**Routing key: `(stream_type, event_type)`, never `event_type` alone.** `events.event_type` stores the unqualified class name; a cross-BC name collision is plausible.

**Schema evolution: weak schema first; new event type for breaking changes.**

1. **Default**: weak schema, additive only. Add optional fields; the evolver supplies a default for old events.
2. **Breaking changes** (rename, type change, semantic change): a new event type. Stop emitting the old one; the evolver handles both forever. A future `ThingRenamed` is a new event class on the union, not a `name` field added to `ThingRegistered`.
3. **Upcasters only when warranted.** Once two breaking changes hit the same logical event, a `from_stored` dispatch table is fine. The `schema_version` field is the trigger.

Why: events are immutable, value objects evolve. The evolver re-validates payloads on read by reconstructing them (`Thing(name=ThingName(event.name))`). New event types are explicit at the union, and pyright's exhaustiveness check forces handling.

**`event_id` is the dedup key.** Producers generate one fresh UUIDv7 per event via the `IdGenerator` port; the events table has UNIQUE on `event_id`. Subscribers dedupe by `event_id` against their checkpoint. Polling by `position` must also handle the bigserial sequence-rollback hazard documented in `keeper/infrastructure/ports/event_store.py`.

**Collection fields on event payloads use immutable types**: `tuple[X, ...]` instead of `list[X]`, `frozenset[X]` instead of `set[X]`. The fold step shares the payload's collection reference into the new aggregate state; a mutable collection invites alias bugs where mutating the state silently mutates the event dict that built it, or the reverse. To be pinned by a fitness test once events exist; unenforced today.

**`from_stored` wraps go through the canonical helper** at `keeper.infrastructure.event_payload.deserialize_or_raise(event_type, builder, *, extra=(), message_suffix='')` for event-arm wraps, and the sibling `deserialize_vo_or_raise(vo_type, builder, *, extra=(), raise_as=ValueError)` for nested value-object deserializers. Both raise `ValueError("Malformed <type>")` with no payload echo, so an exception log cannot leak a correlatable identifier. The `extra` parameter accepts additional exception classes an inner `Enum(...)` constructor or typed deserializer might raise; `raise_as` preserves typed exception subclasses.

**Dict fields on event payloads** are not pinned by the fitness test, because JSON-schema-shaped payloads are intrinsically freeform. The companion defence is **shallow-copy on fold** at the evolver: `field=dict(payload_field)`, or `dict(payload_field) if payload_field is not None else None` for optional dicts. Apply it at every site where a dict-typed payload field maps into aggregate state.

## Value objects

Live at the smallest scope owning the invariants. See [Layout](layout.md#where-shared-code-goes) for the scope table.

**Trimmed-bounded-text value objects share a validation helper, not a base class.** They call `keeper.shared.bounded_text.validate_bounded_text`:

```python
@dataclass(frozen=True)
class ThingName:
    value: str

    def __post_init__(self) -> None:
        trimmed = validate_bounded_text(
            self.value,
            max_length=THING_NAME_MAX_LENGTH,
            error_class=InvalidThingNameError,
        )
        object.__setattr__(self, "value", trimmed)
```

Each value object keeps its own frozen dataclass type, per-aggregate error class, and `MAX_LENGTH`. A shared base class would couple aggregates; a class factory would weaken `isinstance`. A free function avoids both.

**Primitives in events, value objects at state and decider boundaries, except for a closed vocabulary.** Events carry primitives (str, int, UUID, datetime, dict), never value objects. The decider unwraps: `ThingRegistered(name=thing_name.value)`. The evolver re-validates: `Thing(name=ThingName(event.name))`. The round-trip test at `tests/unit/<bc>/test_evolver.py` verifies this per aggregate.

The carve-out: a field whose VALUE SET is closed, a `StrEnum`, or a frozen value object every one of whose fields is closed by construction, may be declared on the event as that type directly. Two conditions must both hold:

1. **A consumer resolves the field's meaning from its declared type.** A record exporter that decides publishability from the declared type sees a field wrapped down to bare `str` as unpublishable by construction, even when its own constructor already closes its range. A closed type declared honestly keeps that information.
2. **The type must be reachable from wherever the event class lives.** A BC's `aggregates` namespace has a narrower dependency allowance than the feature layer above it. A closed type that is not SAFELY reachable stays a primitive; that is the ordinary rule, not an exception to it. Do not mirror a sibling BC's enum locally to dodge the reachability limit: the mirror will raise on the first member it has not caught up to.

When a build-time consumer needs to ask a type object whether it closes its own range, give it a marker base class to check rather than a list of class names to maintain. Do not add that marker before the consumer exists: a marker nothing reads is a claim nothing tests.

A second, narrower reason to declare a value object directly on an event even when it is NOT closed: a `dict`/`Mapping`-typed field resolves to opaque as a whole, so a structured carrier with a MIX of closed and open leaves loses the closed ones too unless the consumer can see the mix. Typing the carrier keeps the closed leaves legible.

When a genesis command carries two sibling freeform carrier dicts and only one gets this treatment, the dividing line is real writer content, not a coin flip: type the one a production writer actually populates with a stable shape today, and leave the other opaque until one does, rather than inventing a shape ahead of demand.

## Field grouping

Default to **flat fields** until three members of a group exist. Then hoist into a value-object holder.

```python
# 1 member: flat
@dataclass(frozen=True)
class Thing:
    required_part_ids: frozenset[UUID]

# 2 members: still flat
@dataclass(frozen=True)
class Thing:
    required_part_ids: frozenset[UUID]
    required_inputs: frozenset[str]

# 3+ members: hoist
@dataclass(frozen=True)
class Needs:
    part_ids: frozenset[UUID]
    inputs: frozenset[str]
    fixture_ids: frozenset[UUID]

@dataclass(frozen=True)
class Thing:
    needs: Needs
```

Why flat: Pydantic and MCP schemas read naturally, event payloads are append-only, and one-field wrappers are ceremony. Why hoist at three: the field-list noise crosses the threshold where reading state takes a second pass.

**Migration when hoisting:**

1. Define the holder value object in `aggregates/<aggregate>/state.py`.
2. Add an additive `<group>` field, default-constructed; keep the flat fields.
3. The evolver populates both flat and grouped from the same payload.
4. Migrate readers to the grouped form.
5. In a cleanup commit, remove the flat fields.

Event payloads stay flat; the holder is a state-side ergonomic.

## Choosing where an act is recorded

When two aggregates could plausibly record the same act, select on the act's **output of record**, not on how the act was driven or how big it is. Write the discriminating question down as a single observable fact, and make it answerable without reading the implementation.

Two axes are commonly conflated with that selection and should be kept separate:

- **Who drove the act.** Whether the system conducted it, or was told afterwards that something else did, is orthogonal to which aggregate owns the record. Both modes belong to whichever aggregate the output test picks. The two are named **conducted** and **reported** in the [Glossary](glossary.md).
- **How the act reached its substrate.** The port an act travelled over is an adapter concern. It never decides the aggregate.

Data that merely transits an act is not an output of record. When an act computes a value from intermediate artifacts it does not retain, the value is the output and the artifacts are not.

Selecting on a single observable fact is what keeps long-horizon ledger queries unique: the same act never lands in two places.
