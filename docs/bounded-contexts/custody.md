# Custody

Custody is the bounded context that answers one question: where is the data one run produced, and who is keeping it?

It holds one aggregate, the Dataset, and six things you can do to it. The record is deliberately small, and most of this page is about what is not on it.

## What a Dataset is

A dataset is one body of data one run produced, as this system came to know about it.

```
   Dataset
     id            a UUID minted when the record is written
     execution_id  the traversal it came out of
     step_id       the run within it that produced it
     external_refs every address a store holding it answers to
     description   what was inside one copy when somebody looked, or nothing
```

Four fields. Two are references to things this system does not hold, and the fourth is a report about something it cannot read. None of them is the data, which is the shape of the whole context.

`external_refs` is plural because one body of data is commonly at two addresses at once. A copy to central storage leaves the beamline copy in place until something purges it, and that window is days to weeks, which is also the window in which anything would want to read it. A single address would have to be swapped at the moment of the copy, and the swap is wrong for the whole of the window: it says the data left a disk it is still on.

## Why it holds so little

The store holds the data, its size and its metadata, and it is addressable. Anything copied here would be a second copy of a fact somebody else owns, and it would go stale the first time they changed it. That is the same argument [Access](access.md#why-it-has-no-name) makes about an actor's name, applied to a much larger surface.

What no store holds is which run produced what it is keeping. A store was handed an engine's own identifier, and this system is the only place that identifier has been resolved to something it composed. **The join is the whole of what this context adds**, and every field that is not the join was left out on purpose.

### The one clause that was reversed

That paragraph used to refuse a dataset's shape alongside its size and its metadata, and the description is that refusal narrowed. It is recorded here rather than quietly dropped, because a reversal a reader cannot see is how a rule turns into folklore.

The clause rested on "and it is addressable", which assumes there is an owner to go and ask. At the beamlines this serves there is not. The data sits on a local disk, nothing answers questions about it, and a reader standing anywhere else cannot open it to learn whether it is even usable. The refusal existed to stop this record duplicating a fact somebody else holds, and here nobody else holds it.

So a description is admitted as the same kind of fact an address already is. Both say what was true at a moment, both are superseded by a later event rather than edited, and neither substitutes for reading the data. One says where it is, the other says what shapes are in it, and a reader wanting a number still has to go and open it. A cache claims to be the value; an index helps a reader find it and never stands in for it.

What stays refused is anything computed from the data, and that part is a shape rather than a sentence. An entry has a path, an extent and a role, and there is nowhere in it to put a mean.

The admission is expected to narrow again. A deployment whose store serves structure of its own has an owner for the dimensions, and a reader asking that store reports the roles and leaves the numbers out. The entry already allows that, so the day it happens costs no new event and no migration.

### Why a step and not a whole execution

An execution may hold a thousand steps and run several times, and each run writes its own data. A reference to the execution alone would say that these five datasets came out of this traversal and nothing about which came from where, which at a tomography beamline is the sample position: the one thing that makes the data interpretable.

### Why both ids

`step_id` is unique and is enough to look a step up. It is not enough to check one. A step is an entity inside the Execution aggregate rather than a stream of its own, so establishing that it exists means loading the execution that holds it, and the registering handler does exactly that. The root comes first and the step qualifies it, which is the order every other cross-aggregate reference in this tree reads in.

Both are this system's ids, not the engine's. Whatever reports a dataset holds the engine's uid and resolves it first, and storing the uid instead would put a second unresolved reference on the record and leave the join to every later reader.

## Why this is not called Provenance

Provenance is the word most people reach for, and it claims more than this context carries. Provenance is the whole causal graph, and two thirds of it are already elsewhere in this tree: the agent is an Actor in Access and the activity is an Execution in the context of that name. A context holding the third part and named after the whole would be the same kind of overclaim that [Execution](execution.md#this-system-owns-every-genesis) rejected when it declined "witnessed".

Custody says what this one can back: where the thing is, and on whose word. It is also the right word for what comes next, because data that moves, is withdrawn, or is superseded by a reprocessing are all custody events and none of them is a provenance event.

## The operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Register a dataset | `POST /datasets` | `register_dataset` | `201` with the new id |
| Read one back | `GET /datasets/{dataset_id}` | `get_dataset` | `200` with the dataset |
| Find what one run produced | `GET /datasets` | `list_datasets` | `200` with a page of datasets |
| Record another address for it | `POST /datasets/{dataset_id}/addresses` | `register_dataset_address` | `204` |
| Record that an address stopped answering | `POST /datasets/{dataset_id}/addresses/withdraw` | `withdraw_dataset_address` | `204` |
| Record what is inside one copy | `POST /datasets/{dataset_id}/manifests` | `register_dataset_manifest` | `204` |

Each is published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `src/keeper/custody/routes.py`.

`POST /datasets` creates a record of something that already exists elsewhere, not the data. Nothing here reaches the store and nothing here could: a caller that can see the data is the one that knows its address.

The two address operations hold the same posture one level down. Neither moves or deletes anything. Something else copied the data or purged it, and these record that it happened, which is why both accept an `occurred_at` the caller supplies. Both answer `204`: an address has no id of its own, it is named by the scheme and value the caller already holds.

Withdrawal is a `POST` carrying a body where the nearest sibling in this tree revokes a permission with a `DELETE` on a path. The difference is what names the thing being removed. A permission is named by two safe identifiers; an address is named by a store's own spelling, which routinely carries slashes. A body also keeps the reference nested, which is what stops a caller expressing half of one.

## Registered, and why that verb takes a timestamp

The genesis is `register_dataset`, producing `DatasetRegistered`. The glossary's read-aloud test is what settles the verb: "define a dataset" sounds like inventing data, which this system did not do and could not, while "register a dataset" sounds like filing something that came from elsewhere.

That makes it **the first `register_*` in this tree that describes a fact rather than making one**, and the consequence is visible in the signature. `register_actor` takes no `occurred_at`, because an actor's registration is an act this system performs and the moment it writes one is the moment it happened. A dataset was written somewhere else, at a moment this system was not present for, so the caller may say when. See [R8](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one), which draws that line on the makes-versus-describes axis rather than on the verb, and the Time section in [Conventions](../reference/conventions.md#time), which lists the commands on each side.

Reported is also permanent here, unlike in Execution. Even a deployment where this system dispatched the run would not have written the data: some writer did, and this context would still be hearing about it afterwards. So no prefixed sibling is coming to sit beside this command.

## What the stream holds

There is no datasets table. Current state is recomputed by replaying a stream on every read.

```
   DatasetRegistered   dataset_id, execution_id, step_id,
                       external_ref_scheme, external_ref_value, occurred_at
   DatasetAddressRegistered   dataset_id, external_ref_scheme,
                              external_ref_value, copied_by_execution_id,
                              copied_by_step_id, occurred_at
   DatasetAddressWithdrawn    dataset_id, external_ref_scheme,
                              external_ref_value, occurred_at
   DatasetManifestRegistered  dataset_id, external_ref_scheme,
                              external_ref_value, convention, entries,
                              occurred_at
```

Each reference travels as two flat strings and is rebuilt into a pair by the fold, because events carry primitives and that pair is a value object.

Four events, and the three later ones add an address, remove one, or report what was inside one, rather than editing the row before them. A record saying where data was at a moment stays true when the data moves, and what changes is that there is a later fact. Registered and withdrawn rather than one moved event, because a copy and a purge are separated by days and both are true in between. An address rather than a copy, because the same bytes answer to a local path, an NFS path and a server URI at once, and what a reader needs to know is which of them it can reach.

`copied_by_execution_id` and `copied_by_step_id` are optional together, and the optionality carries a meaning worth stating. A copy this system dispatched is a report it is owed and names the step that made it. A copy somebody else made is something this system was told, and most copies are that: facility data movement runs on its own and will never be a principal in this record. Absent has to mean absent, because a citation naming an execution that did not do the copying reads as a report this system went and asked for.

`entries` is the one nested payload on this stream, and it is typed rather than left a list of dicts. The rule is primitives on events, and its carve-out is what applies: a field typed as a bare dictionary is opaque as a whole, so a carrier mixing closed leaves with open ones loses the closed ones too. A path and an extent are shapes this system refuses out of range, and a role is a word from a vocabulary nobody here owns. The steps on a procedure get the same treatment for the same reason.

A dataset can run out of addresses, and the empty tuple is not a broken record. It says this system knew where data was, every copy it knew of is gone, and the run that produced it is still named. That is more useful than a deleted row, which would answer "what did this run produce" with silence.

## Who owns the shape of the reference

Each entry in `external_refs` is the same open-scheme pair an execution's engine reference is drawn from. The scheme names the vocabulary and the value is opaque to this system, which is not laziness about validation but the layering: how a particular store spells an address is that store's fact, and a rule stated for one store reads as a rule derived from one.

It has a consequence worth stating plainly, because it is the failure mode rather than a hypothetical. **A producer that reports the same body of data two ways makes two records of it, and nothing here can tell.** A store whose client reports one address in two spellings is a real thing; settling on one belongs to whatever writes the record, before it writes it. `Identifier` does no more than trim and bound what arrives.

## What is inside, and what the record will not say about it

A description is what somebody found when they opened one copy. It carries the convention its names follow, the copy that was opened, when it was read, and one entry per thing worth naming.

```
   Description
     external_ref  which copy was opened
     convention    the vocabulary the roles below are drawn from
     described_at  when the container was read
     entries       path, extent, role
```

Three things about it are deliberate and each one is load-bearing.

**It is as of a moment, and never claims to be current.** A container can change after it is described, and one kind here does: a scan engine at some of these beamlines reopens a finished file to append the rotation angle of each frame. A description taken before that is not wrong, it is early, and a later description is a later event rather than an edit. That is why the copy and the moment travel with it.

**An absence is the most useful thing it carries.** A report says what was there, never what a convention says should be there. A complete set of frames with no rotation angles beside them cannot be reconstructed, and today nothing notices until somebody tries. An entry with no role is the other direction: something present and not recognised is named and counted rather than left out.

**There is nowhere in it to put a value read out of the data.** An entry is three fields and a mean does not fit in any of them. That is the rule this whole shape exists to enforce, and it is a closed dataclass rather than a convention, because a rule can be read and ignored. A description must be enough to decide whether to open the data, and never enough to answer instead of opening it.

The vocabulary the roles come from is not defined here and should not be. It accretes, the way the free-form `group` on a device register has been accreting with four beamlines independently reaching the same word. A word several readers reach for has earned agreement; a word one reader reaches for costs nothing. It is also the only part of a description that no store will ever own, which is why it is the part that has to be in the record.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidIdentifierError` | 400 | The external reference had an empty or over-long half. |
| `InvalidOccurredAtError` | 400 | The reported timestamp carried no timezone. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `RunNotFoundError` | 404 | The id names no run. |
| `DatasetNotFoundError` | 404 | The id names no dataset. |
| `DatasetAlreadyExistsError` | 409 | Registration was aimed at an id that already has a history. |
| `DatasetAddressKnownError` | 409 | The dataset is already recorded at that address. |
| `DatasetAddressUnknownError` | 409 | An address was withdrawn, or described, that the dataset does not hold. |
| `DatasetDescriptionUnchangedError` | 409 | A description arrived saying what the record already says. |
| `InvalidManifestError` | 400 | A description was outside what one may hold. |
| `InvalidCursorError` | 422 | The page cursor is not one this system issued. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

**Four of these are not this context's classes, and it registers none of them.** `InvalidIdentifierError` belongs to the shared value object, `InvalidOccurredAtError` and `RunNotFoundError` to Execution, and `InvalidCursorError` is cross-BC infrastructure registered once at the composition root. FastAPI's exception handlers are app-scoped, so the context that owns each one maps it for the whole application, and a second registration here would be the duplicate [Patterns](../reference/patterns.md#rejections) warns about. The contract tier walks all four over a Custody route, because whether that reliance actually holds is not something the source can state.

The 400 group of this context's own holds exactly one entry, and it arrived late. There was none for as long as the record held nothing but a reference to something it cannot read, which left nothing of its own to declare malformed. A description is the first thing here that is its own and can be ill-formed: too many entries, a container counted by two numbers, a role that is a payload rather than a word.

`DatasetDescriptionUnchangedError` is the one refusal on this aggregate that needs its reason stated, because it looks like the opposite of what the description is for. A description that **differs** is admitted however often, since looking twice and seeing two things is the case worth keeping. What is refused is a description identical to the one already held, which is what an at-least-once producer sends when a response was lost, and appending it would grow the log a row per delivery while changing no state.

Reading is gated like writing. A dataset record says that a particular run produced data and says where that data is kept, which is two things a deployment should get to decide who may learn.

## Why one dataset per run is a caller's policy, not a rule

Nothing here says a run has one dataset, or that two datasets may not name the same address. Both are true of the reporting side today and neither is enforced, and the distinction matters because one of them was nearly frozen into the schema.

The stream id is a fresh `IdGenerator` id and is **not** derived from the step id. Deriving it, which is Variant A in [Patterns](../reference/patterns.md#cross-stream-uniqueness), would have made one-per-run a permanent property of the identity scheme from the first migration. It is not, so the two ids are ordinary fields and many-to-one is already the shape on disk. Changing the policy later costs a sentence in the reporter rather than a migration.

What stands between an at-least-once producer and two records of one body of data is the idempotency key, and only that. Nothing in this context refuses a duplicate on its own, because one stream cannot see another. A producer that derives its key from the step and the store's own address recomputes it after any restart having persisted nothing, which is what makes redelivery safe. Both halves, because either alone collapses a real pair: a key without the address turns a run that wrote two datasets into one record, and a key without the step turns two runs that wrote one address into one, which an engine whose scan number resets does every time it comes back. That is a heavier load than the same wrapper carries elsewhere, and it is why the integration tier pins it against a real key store rather than a dictionary.

## What it reaches across for

Execution, in one direction, for two names. Nothing in Execution reaches back.

```
   execution.load_execution   refuse a dataset citing a step that is not there
```

This is the second cross-context door in the tree and the doors are declared in `tach.toml`. The first, from Authority into Access, exposes one name.

`load_execution` is an existence check and nothing more, made twice: that the execution is there, and that it holds the step named. `register_dataset` has no `context.py`, which is the difference from `define_procedure` next door: that slice loads an operation per run because its decision reads their schemas, so sibling state is an input. This decision needs nothing from the execution. Existence is the handler's to check and state is the decider's, which is the split [Patterns](../reference/patterns.md#cross-aggregate-validation) draws between a 404 and a refusal, and a context holder carrying a value nothing reads would be a door held open for nobody.

The door was one name wider. `normalize_occurred_at`, which this context's registering command calls to turn a claimed moment into an instant, came through it until a third consumer arrived. It is pure and has no `keeper` imports, so by the table in [Layout](../reference/layout.md#where-shared-code-goes) its home was always `keeper/shared/`, and the rule of three is what held it next door until [Counsel](counsel.md) met it. It is `keeper.shared.instant` now, which every module may import without an edge, and this command imports it like any other shared helper.

## Finding one without its id

Reading a dataset by id replays one stream and answers from it, which costs one query and stays correct forever because the stream is the record.

The question this context exists for cannot be answered that way. "What did this run produce" names a step, not a dataset, and a fold has to know which stream to fold. So there is a second read path, the same shape [Execution](execution.md#finding-one-without-its-id) built for the same reason:

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

**The summary carries everything except what is inside.** A run summary drops the parameters, because they are unbounded and a page would be mostly parameters. A dataset used to have nothing to drop, and now it has one thing: fifty rows each carrying eight entries would make a listing mostly entries, which is the same argument one level down. A caller that wants to know what is in a dataset reads that dataset. The listing answers what a run produced.

**The row has one timestamp.** `created_at` and no `updated_at`, and the absence belongs to the aggregate rather than to the row. A dataset's own fields never change. What changes is which addresses it is reachable at and what somebody last found inside one, and both are facts about those rather than about the dataset, so one column dating the newest of them would read as though the record had been edited.

**The projection subscribes to three event types and has three arms**: a dataset appears, gains an address, loses one. No transitions and no derived status, because the only thing it reports is where the data can be reached. It does not subscribe to the fourth event, so a description reaches a reader through the record and not through this table. The `ON CONFLICT` is load-bearing, because delivery is at-least-once, and the integration tier rewinds a bookmark and replays a real batch to prove it.

## Where the code is

```
   src/keeper/custody/
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
       register_dataset_address/   another place the data answers to
       withdraw_dataset_address/   one that stopped answering
       register_dataset_manifest/  what somebody found inside one copy
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

## What is not here yet

A caller for the two address operations. The doors are open on both surfaces and nothing at a beamline calls them yet, because nothing there moves data off local disk today. The first caller is whatever does.

Superseded, which is the third plausible event and is not designed. A reprocessed dataset standing in for an earlier one is a relationship between two records rather than another address on one, and nothing has asked for it.

Anything a reader could use instead of opening the data. The description says what shapes are in there and what a convention calls them. It says nothing about the values: no statistic, no sample, no summary of content. That line is the difference between an index and a cache, and it is held by the shape of an entry rather than by this paragraph.

A description per copy. The record keeps the latest, whichever copy it was taken of, because the copies of one dataset are the same bytes by this record's own account. The event names the copy it was taken of even so, so the day a deployment converts data as it copies it, keeping one description per address is a change to how the stream is folded and not a new kind of row.

Any way to ask which datasets are missing a description, or which hold projections with no angles beside them. Both are the questions worth asking and neither has a query. The shape of the answer is the one [Execution](execution.md) already built for runs whose output nothing recorded, and it arrives when something is filing descriptions regularly enough for the gap to mean anything.

Any notion of which store. The scheme half of the reference names a vocabulary, not an instance, so two stores addressing data the same way are indistinguishable on the record. A deployment serving two runs two reporters with two schemes, which holds until something inside this system needs to tell them apart.

Any way to find a dataset by its address. The list filters on the step and on nothing else, and the table carries no index on the reference, because nothing asks: a producer wanting to know whether it already registered an address uses its idempotency key, which answers without a query. It is a column and a filter when somebody needs it.

Anything a projection could answer beyond finding a record: how much one run produced, which runs produced nothing, what landed last week. The table has the columns for none of those.

Any check that a reference resolves. Nothing here can reach the store, so a record can point at data that was deleted an hour later and nothing will notice. Closing that needs something watching rather than another field.
