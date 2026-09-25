# Glossary

Each term defined once and used the same way in code, commits, and prose. Names are load-bearing; drift in vocabulary is drift in the model. If a page uses a term differently, the page is wrong.

The glossary covers the chassis, plus the domain vocabulary of each bounded context that has landed. A term is not in the model until it is here.

## Project name

- **Keeper.** This project. The system of record for the experiment, and a parallel modeling effort on the architecture described in these pages. Its chassis was copied once from the sibling project CORA, which is not public.
- **CORA.** The sibling project this chassis was copied from. The keeper owns its copy outright; the two share no code and are free to diverge. When these pages cite a convention as inherited, CORA is where it came from.

## Architecture

- **Bounded context (BC).** A self-contained slice of the domain with its own model, language, and API surface. One Python package under `keeper/`.
- **Aggregate.** Consistency boundary inside a BC. Holds state, validates commands, emits events.
- **Decider.** Pure `(state, command) -> events`. Business rules. No I/O.
- **Evolver.** Pure `(state, event) -> state`. Folds events into state.
- **Fold-on-read.** Rebuild aggregate state by replaying its events on every command. No snapshots.
- **Vertical slice.** One folder per command or query: `command.py`, `decider.py`, `handler.py`, `route.py`, `tool.py`.
- **FCIS.** Functional core, imperative shell. Pure deciders and evolvers; all I/O at the shell through injected ports.
- **Port.** A `Protocol` defining a side-effect seam: `Clock`, `IdGenerator`, `EventStore`, `Authorize`, `IdempotencyStore`, `TokenVerifier`, and the rest.
- **Adapter.** A concrete implementation of a port. Named `<Tech><Port>`, with no suffix: `PostgresEventStore`, `JwtTokenVerifier`, `InMemoryIdempotencyStore`.
- **Kernel.** The shared kernel: the cross-BC primitives every `wire_<bc>(deps)` pulls from. Settings, clock, id generator, authorize, event store, idempotency store, connection pool.
- **Composition root.** `infrastructure/deps.py` plus `api/main.py`. The only place that constructs adapters and binds them to ports.
- **Handler.** The imperative shell for one slice: loads state, calls the pure decider, appends the resulting events. Not an endpoint; the route is the endpoint.
- **Wire.** A BC's `wire.py`, which builds the BC's handler bundle from the kernel. Also the verb for that act.

## Execution

- **Plan.** A runnable routine this system holds a record of: the name the engine knows it by, and the JSON Schema a run of it must satisfy. Defined, not registered: nothing anywhere pairs that name with that schema until the record says so.
- **Routine.** The thing out in the engine that a plan's name points at. Not modelled here, and named with a plain word rather than a term, because this system holds a reference to it and never the thing itself.
- **Procedure.** A routine this system composed, written down: an ordered list of steps, each naming what it touches. The contrast with a **plan** is who authored the routine. A plan names something an engine already has and a procedure names something nothing knows until this system says so, which is why a plan's name is a handle in someone else's vocabulary and a procedure's steps are not.
- **Step.** One element of a procedure. Two kinds: a **move**, which sends one record to one value, and an **acquisition**, which asks an engine to run a plan. Only an acquisition declares the devices it touches, because only a move's are derivable from the step itself.
- **Scope.** One piece of a device namespace, named as a string and claimed whole. Stored here as written and parsed nowhere: the grammar belongs to whatever drives the procedure, and the arithmetic over collisions runs in that process.
- **Execution.** One traversal of a procedure: the record this system opens when it dispatches one, and how far the thing driving it got. Every step of it is either reported by a driver or left unreported, and the record says which.
- **Execution status.** How far an execution has got: Dispatched, Claimed, Running or Ended. Derived in the fold from which events the stream carries, never stored. Dispatched is the one transient state in this tree: the record exists and nothing has taken it up, which is a state that only becomes possible once this system hands work out.
- **Engine state.** What an engine was reported to have done to the run one acquisition step opened: Running, Paused, Completed, Aborted or Failed. The second of two observers of one step, beside the driver's outcome, and the two are allowed to disagree because neither is reliable and collapsing them would make this system pick a winner between two claims it cannot check.
- **Run.** Retired. It was one carrying-out of one plan, recorded because an engine had run something and this system was told. It and an acquisition step turned out to be the same fact in two vocabularies once this system started composing the work, so the step is what remains. The word still means what it always did when an engine says it, which is why a step carries an `engine_reference` and an engine state.
- **External reference.** An open-scheme `(scheme, value)` pair naming something in a system outside this one. The scheme names the issuing authority and the value is opaque to it. A dataset carries one, because data this system cannot point back at cannot be found.
- **Reported.** Of a step or of an engine's account of one: performed somewhere else, and made known to this system by someone or something telling it afterwards. The contrast pair is **composed**, of the work this system authored itself. It claims only what this system can back: that it was told. "Witnessed" would fail that, because to witness is to have been present and able to vouch, and this system was neither.
- **Engine.** Whatever actually runs a routine, outside this system. Named by role rather than by product, because which one a deployment runs is a deployment's fact.

## Custody

- **Dataset.** One body of data an acquisition produced, as this system came to know about it: which step made it, and what the store holding it calls it. Not the data, and not a description of it. The word is the one people say out loud for this thing, and it is defined here rather than avoided because the store's own vocabulary uses it for something narrower; nothing in this system imports that vocabulary.
- **Store.** Whatever actually keeps the data an acquisition produced, outside this system. Named by role rather than by product, for the same reason **engine** is: which one a deployment runs is a deployment's fact. The contrast with an engine is what each one is asked for, not how either is reached.
- **Custody.** Of data: the fact of somebody holding it, and the record of who and where. Chosen over **provenance**, which names the whole causal graph and would claim two thirds this context does not carry, the agent being an actor in Access and the activity an execution in the context of that name. Custody also keeps its meaning as the record grows, because data that moves or is withdrawn changes who holds it and changes nothing about where it came from.
- **Data custodian.** Not a term in this model, and listed so the collision is on the record. In facility governance it means whoever is accountable for data, which is a question about permission and belongs to Authority. Custody here is about location and possession, never about who may act.

## Counsel

- **Proposal.** A run an agent put forward, before anything has run it: which plan, with what values, who advised it, and the acquisition that took it if one has. It cites a plan and does not contain one, which makes it an acquisition step's two fields without the fact of the step having happened. A proposal refers to no act at all, which is the whole distinction between them.
- **Counsel.** Advice given, and the record of it: who advised, what they put forward, and whether anything came of it. Chosen over **Direction**, which at a synchrotron is a vector, and over **Initiative**, which also means a campaign and so collides with the aggregate this context defers. It claims only the advice and never the weighing, which happened inside an agent over data this system never saw, so it passes the same test that picked **Custody** over provenance. It still fits on the day this system drives the engine, because the counsel stays the agent's and the driving is Execution's.
- **Taken.** Of a proposal: an acquisition step exists that ran what it proposed. Not **accepted**, which says a party considered it and said yes, and nobody did: whoever composed the procedure may simply have gone ahead. That word is reserved for approval by a person, which is a real future event on this stream and a prior one, because an operator can approve something that then never runs.
- **Open.** Of a proposal: no acquisition has been recorded against it. Derived from the reference being absent rather than stored as a status, so it cannot disagree with the join it reads. It says only that nothing has been recorded, the way an execution's Dispatched does, so a proposal nobody acted on reads as open forever.

## Equipment

- **Device.** One piece of hardware this system holds a record of: where its control system publishes it, this system's label for it, and what it was last reported doing. Not the hardware, and not its readings. The word collides with the class name a control library gives its own composite objects, and it is used here anyway on the same grounds **Dataset** is: it is what people say out loud for this thing, and nothing in this system imports that library's vocabulary. What the library means by it is narrower and client-side, which is the point of the collision rather than an awkwardness around it.
- **Equipment.** The hardware a facility has, and the record of what state it is in. The word appears in the sibling project for something of its own, and arriving at it here is convergence rather than inheritance: two projects reaching the same ordinary noun for the same real thing. It was on the banned-vocabulary list until this context landed, which is the move that list reserves for a term this project comes to model itself.
- **Control system.** Whatever actually drives and publishes a device, outside this system. Named by role rather than by product, for the same reason **engine** and **store** are: which one a deployment runs is a deployment's fact. The contrast with the other two is what each is asked for, not how any of them is reached.
- **Device status.** Where a device stands: Available, Faulted or Retired. Derived in the fold from which events the stream carries, never stored, so it cannot disagree with the history behind it. Available says only that no fault has been reported and none stands, which is a claim about what this system has been told rather than about the hardware. Faulted is the only one of the three that is a claim about the world at all; the other two are this system's own bookkeeping.
- **Fault.** Of a device: something was reported wrong with it. The reporter's judgement rather than a value copied through, because what a control system publishes is an alarm severity and an alarm is not a fault. The same judgement a reporter already makes when it picks one of an engine's three terminals, and the reason no severity reaches the record.
- **Recovered.** Of a device: it came back from a fault. Not **restored**, which says somebody did something, and usually nobody did: the condition ended. Fault and recovery is the pair an operator already uses, and it is the one edge on this machine that points backwards, so a device's status is not monotonic even though its stream only grows.
- **Retired.** Of a device: this system no longer counts it as present. Not **withdrawn**, which is what happens to a proposal here and is defined once. Not **removed** either, which would claim the hardware left the beamline, a different fact at a different moment that this system was not present for. Retiring is not deleting: the stream stays and the history stays readable.

## Events

- **Event store.** Append-only Postgres table of immutable events. INSERT-only at the database role level, not merely by convention.
- **Stream.** All events for one aggregate instance, ordered by version.
- **Stream type.** The aggregate kind a stream belongs to. Routing is on `(stream_type, event_type)`, never `event_type` alone.
- **Position.** Global monotonic ordinal of an event in the store. Subject to a bigserial sequence-rollback hazard that projections must handle.
- **transaction_id (xid8).** Postgres transaction identifier carried on every event. Lets a projection worker advance a cursor without skipping in-flight inserts.
- **Envelope.** The persistence wrapper around a domain event: stream coordinates, correlation and causation ids, principal, timestamps and schema version.
- **Projection.** A read model built by replaying events into a denormalized table. Workers tail the store and advance a bookmark.
- **Bookmark.** A projection's durable cursor in `projection_bookmarks`. One of two things this vocabulary calls a cursor; the other is below.

**Page cursor.** An opaque token a list endpoint hands back, encoding the sort key of the last row it returned. A caller passes it to get the next page. Unrelated to a bookmark: a bookmark is how far a worker has got through the log, a page cursor is how far a reader has got through one query's results.

**Read port.** A Protocol a bounded context declares over its own read model, so a slice depends on the question rather than on the table. Two implementations, one per environment: the projection in a deployment, a fold over the streams where there is no database.
- **Entries table.** A typed append-only table for rows a slice writes directly, without a decider. Distinct from `events`: events record what was decided, entries record what was done.
- **Upcaster.** A `from_stored` dispatch arm that reads an older payload shape. Introduced only once a second breaking change hits the same logical event.

## Surfaces

- **REST.** FastAPI HTTP endpoints under `/<resource>`. OpenAPI at `/docs`.
- **MCP.** Model Context Protocol, the agent surface. Streamable HTTP at `/mcp`. Same handler as REST, never a parallel implementation.
- **Surface id.** Identifies the ingress shape a call arrived through. Threads through every handler, the `Authorize` port, and the idempotency cache key namespace.
- **Principal.** The authenticated caller, as a UUID. Set by the bearer middleware, or by a verifying proxy on the header path.

## Testing

- **Fitness function.** An architecture test that asserts a structural rule rather than a behavior. Lives in `tests/architecture/`, does no I/O.
- **Vacuous pass.** A fitness function that passes because it found nothing to check. The default state of this repository until the first BC lands, and the reason `test_fitness_scope.py` exists.
- **Tier.** One of the five test directories: `unit`, `architecture`, `integration`, `contract`, `e2e`. The marker is the category; the test name is the property.
- **Create-style slice.** A slice whose verb is `define_*`, `register_*`, or `add_*`. Introduces a new stream, so it carries an idempotency key and a Postgres-backed handler test.

## Conventions

- **Rule of three.** Promote a shared abstraction only after three real usages with identical, stable invariants. Applies to value objects, handler factories, ports, and helper modules.
- **Forward-only.** A migration is never edited after it has been applied anywhere. A rollback is a new compensating migration.
- **Genesis event.** The first event on a stream. `<X>Defined` when the thing is authored here and the record IS the thing; `<X>Registered` when the thing exists outside this system and the record enrols it. A policy is defined, because no policy exists anywhere until one is written. An actor is registered, because the person or service account exists whether or not this system has heard of them. Read aloud to check: "define an actor" sounds like inventing a person, and "register a policy" sounds like filing one that came from somewhere else.
