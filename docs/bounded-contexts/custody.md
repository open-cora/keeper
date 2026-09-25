# Custody

Custody is the bounded context that answers one question: where is the data one acquisition produced, and who is keeping it?

It holds one aggregate, the Dataset, and three operations on it. The record is deliberately small, and most of this page is about what is not on it.

## What a Dataset is

A dataset is one body of data one acquisition produced, as this system came to know about it.

```
   Dataset
     id            a UUID minted when the record is written
     execution_id  the traversal it came out of
     step_id       the acquisition within it that produced it
     external_ref  what the store holding it calls it
```

Three fields. Two of them are references to things this system does not hold, which is the shape of the whole context.

## Why it holds so little

The store holds the data, its shape, its size and its metadata, and it is addressable. Anything copied here would be a second copy of a fact somebody else owns, and it would go stale the first time they changed it. That is the same argument [Access](access.md#why-it-has-no-name) makes about an actor's name, applied to a much larger surface.

What no store holds is which acquisition produced what it is keeping. A store was handed an engine's own identifier, and this system is the only place that identifier has been resolved to something it composed. **The join is the whole of what this context adds**, and every field that is not the join was left out on purpose.

### Why a step and not a whole execution

An execution may hold a thousand steps and acquire several times, and each acquisition writes its own data. A reference to the execution alone would say that these five datasets came out of this traversal and nothing about which came from where, which at a tomography beamline is the sample position: the one thing that makes the data interpretable.

### Why both ids

`step_id` is unique and is enough to look a step up. It is not enough to check one. A step is an entity inside the Execution aggregate rather than a stream of its own, so establishing that it exists means loading the execution that holds it, and the registering handler does exactly that. The root comes first and the step qualifies it, which is the order every other cross-aggregate reference in this tree reads in.

Both are this system's ids, not the engine's. Whatever reports a dataset holds the engine's uid and resolves it first, and storing the uid instead would put a second unresolved reference on the record and leave the join to every later reader.

## Why this is not called Provenance

Provenance is the word most people reach for, and it claims more than this context carries. Provenance is the whole causal graph, and two thirds of it are already elsewhere in this tree: the agent is an Actor in Access and the activity is an Execution in the context of that name. A context holding the third part and named after the whole would be the same kind of overclaim that [Execution](execution.md#this-system-owns-every-genesis) rejected when it declined "witnessed".

Custody says what this one can back: where the thing is, and on whose word. It is also the right word for what comes next, because data that moves, is withdrawn, or is superseded by a reprocessing are all custody events and none of them is a provenance event.

## The three operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Register a dataset | `POST /datasets` | `register_dataset` | `201` with the new id |
| Read one back | `GET /datasets/{dataset_id}` | `get_dataset` | `200` with the dataset |
| Find what one acquisition produced | `GET /datasets` | `list_datasets` | `200` with a page of datasets |

All three are published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `apps/keeper/src/keeper/custody/routes.py`.

`POST /datasets` creates a record of something that already exists elsewhere, not the data. Nothing here reaches the store and nothing here could: a caller that can see the data is the one that knows its address.

## Registered, and why that verb takes a timestamp

The genesis is `register_dataset`, producing `DatasetRegistered`. The glossary's read-aloud test is what settles the verb: "define a dataset" sounds like inventing data, which this system did not do and could not, while "register a dataset" sounds like filing something that came from elsewhere.

That makes it **the first `register_*` in this tree that describes a fact rather than making one**, and the consequence is visible in the signature. `register_actor` takes no `occurred_at`, because an actor's registration is an act this system performs and the moment it writes one is the moment it happened. A dataset was written somewhere else, at a moment this system was not present for, so the caller may say when. See [R8](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one), which draws that line on the makes-versus-describes axis rather than on the verb, and the Time section in [Conventions](../reference/conventions.md#time), which lists the commands on each side.

Reported is also permanent here, unlike in Execution. Even a deployment where this system dispatched the acquisition would not have written the data: some writer did, and this context would still be hearing about it afterwards. So no prefixed sibling is coming to sit beside this command.

## What the stream holds

There is no datasets table. Current state is recomputed by replaying a stream on every read.

```
   DatasetRegistered   dataset_id, execution_id, step_id,
                       external_ref_scheme, external_ref_value, occurred_at
```

One event, because nothing changes a dataset yet. The external reference travels as two flat strings and is rebuilt into a pair by the fold, because events carry primitives and that pair is a value object.

Data that moves or is withdrawn arrives as a new class on this stream when the command that does lands, never as a field edited onto `DatasetRegistered`. That is also the answer to the obvious worry about a store reorganising itself: a record saying where data was at a moment stays true when the data moves, and what changes is that there is a later fact.

## Who owns the shape of the reference

`external_ref` is the same open-scheme pair an execution's engine reference is drawn from. The scheme names the vocabulary and the value is opaque to this system, which is not laziness about validation but the layering: how a particular store spells an address is that store's fact, and a rule stated for one store reads as a rule derived from one.

It has a consequence worth stating plainly, because it is the failure mode rather than a hypothetical. **A producer that reports the same body of data two ways makes two records of it, and nothing here can tell.** A store whose client reports one address in two spellings is a real thing; settling on one belongs to whatever writes the record, before it writes it. `Identifier` does no more than trim and bound what arrives.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidIdentifierError` | 400 | The external reference had an empty or over-long half. |
| `InvalidOccurredAtError` | 400 | The reported timestamp carried no timezone. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `RunNotFoundError` | 404 | The id names no run. |
| `DatasetNotFoundError` | 404 | The id names no dataset. |
| `DatasetAlreadyExistsError` | 409 | Registration was aimed at an id that already has a history. |
| `InvalidCursorError` | 422 | The page cursor is not one this system issued. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

**Four of these are not this context's classes, and it registers none of them.** `InvalidIdentifierError` belongs to the shared value object, `InvalidOccurredAtError` and `RunNotFoundError` to Execution, and `InvalidCursorError` is cross-BC infrastructure registered once at the composition root. FastAPI's exception handlers are app-scoped, so the context that owns each one maps it for the whole application, and a second registration here would be the duplicate [Patterns](../reference/patterns.md#rejections) warns about. The contract tier walks all four over a Custody route, because whether that reliance actually holds is not something the source can state.

There is no 400 group of this context's own, and that is the model rather than an omission. This context holds a reference to something it cannot read, so it has nothing of its own to declare malformed.

Reading is gated like writing. A dataset record says that a particular run produced data and says where that data is kept, which is two things a deployment should get to decide who may learn.

## Why one dataset per run is a caller's policy, not a rule

Nothing here says an acquisition has one dataset, or that two datasets may not name the same address. Both are true of the reporting side today and neither is enforced, and the distinction matters because one of them was nearly frozen into the schema.

The stream id is a fresh `IdGenerator` id and is **not** derived from the step id. Deriving it, which is Variant A in [Patterns](../reference/patterns.md#cross-stream-uniqueness), would have made one-per-acquisition a permanent property of the identity scheme from the first migration. It is not, so the two ids are ordinary fields and many-to-one is already the shape on disk. Changing the policy later costs a sentence in the reporter rather than a migration.

What stands between an at-least-once producer and two records of one body of data is the idempotency key, and only that. Nothing in this context refuses a duplicate on its own, because one stream cannot see another. A producer that derives its key from the store's own address recomputes it after any restart having persisted nothing, which is what makes redelivery safe. That is a heavier load than the same wrapper carries elsewhere, and it is why the integration tier pins it against a real key store rather than a dictionary.

## What it reaches across for

Execution, in one direction, for two names. Nothing in Execution reaches back.

```
   execution.load_execution   refuse a dataset citing a step that is not there
```

This is the second cross-context door in the tree and the doors are declared in `apps/keeper/tach.toml`. The first, from Authority into Access, exposes one name.

`load_execution` is an existence check and nothing more, made twice: that the execution is there, and that it holds the step named. `register_dataset` has no `context.py`, which is the difference from `define_procedure` next door: that slice loads a plan per acquisition because its decision reads their schemas, so sibling state is an input. This decision needs nothing from the execution. Existence is the handler's to check and state is the decider's, which is the split [Patterns](../reference/patterns.md#cross-aggregate-validation) draws between a 404 and a refusal, and a context holder carrying a value nothing reads would be a door held open for nobody.

The door was one name wider. `normalize_occurred_at`, which this context's registering command calls to turn a claimed moment into an instant, came through it until a third consumer arrived. It is pure and has no `keeper` imports, so by the table in [Layout](../reference/layout.md#where-shared-code-goes) its home was always `keeper/shared/`, and the rule of three is what held it next door until [Counsel](counsel.md) met it. It is `keeper.shared.instant` now, which every module may import without an edge, and this command imports it like any other shared helper.

## Finding one without its id

Reading a dataset by id replays one stream and answers from it, which costs one query and stays correct forever because the stream is the record.

The question this context exists for cannot be answered that way. "What did this acquisition produce" names a step, not a dataset, and a fold has to know which stream to fold. So there is a second read path, the same shape [Execution](execution.md#finding-one-without-its-id) built for the same reason:

```
   POST /datasets                    GET /datasets/{dataset_id}
     |                                 fold a stream. Unchanged.
     | event
     v
   events  (the record)              GET /datasets?step_id=...
     |                                 read the table below
     | one worker, one bookmark
     v
   proj_custody_dataset_summary
```

The three things worth knowing before reading a row are the sibling's three, unchanged: **it lags**, so a caller that registers and immediately lists may not see what it just wrote; **it can be thrown away**, because every column is derived from the log and resetting the bookmark to zero rebuilds it; and **it is not a second way to write**, because a handler writing a row directly would be inventing a fact the log does not hold.

Two things are this context's own.

**The summary is the whole aggregate.** A run summary drops the parameters, because they are unbounded and a page would be mostly parameters. A dataset has nothing to drop: two ids and two halves of a reference. That is what a context holding only a join looks like from the read side.

**The row has one timestamp.** `created_at` and no `updated_at`, because nothing changes a dataset yet and a second column would always equal the first. It arrives with the first event that moves one.

**The projection is the simplest in the tree**, and reading it is the cheapest way to see the shape: one subscribed event type, one INSERT, no transitions and no derived status. A context whose aggregate has a single event has a projection with a single arm. The `ON CONFLICT` is still load-bearing, because delivery is at-least-once, and the integration tier rewinds a bookmark and replays a real batch to prove it.

## Where the code is

```
   apps/keeper/src/keeper/custody/
     aggregates/dataset/        state, events, the fold, how to load one, and
                                the summary a list shows with the port over it
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the table in step with the log,
                                and the call that hands it to the worker
     features/
       register_dataset/        command, decision, handler, route, tool
       get_dataset/             a query slice, so no decider: reading decides nothing
       list_datasets/           the query a fold cannot serve
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

## What is not here yet

Anything that changes a dataset. Withdrawn, moved, and superseded are three plausible second events and none is designed. Each arrives as a class on the stream rather than as a field, and the first one to land turns the single-event aggregate into a real one.

Anything about what the data is. No structure, no size, no format, no count. The store answers all of those and this context points at the store. A typed marker saying which kind of thing a node is would be the first field worth adding, and it should not be added before something asks.

Any notion of which store. The scheme half of the reference names a vocabulary, not an instance, so two stores addressing data the same way are indistinguishable on the record. A deployment serving two runs two reporters with two schemes, which holds until something inside this system needs to tell them apart.

Any way to find a dataset by its address. The list filters on the step and on nothing else, and the table carries no index on the reference, because nothing asks: a producer wanting to know whether it already registered an address uses its idempotency key, which answers without a query. It is a column and a filter when somebody needs it.

Anything a projection could answer beyond finding a record: how much one acquisition produced, which acquisitions produced nothing, what landed last week. The table has the columns for none of those.

Any check that a reference resolves. Nothing here can reach the store, so a record can point at data that was deleted an hour later and nothing will notice. Closing that needs something watching rather than another field.
