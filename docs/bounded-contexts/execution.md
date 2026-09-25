# Execution

Execution is the bounded context that answers three questions: what can this system be asked to run, what did it compose out of that, and what happened when the composition was carried out.

It holds three aggregates and fourteen operations across them. A Plan names a routine an engine already has. A Procedure is a routine composed here, out of moves and acquisitions in an order. An Execution is one traversal of a procedure.

The difference between a plan and a procedure is who composed the routine. A plan is a reference to a thing this system did not write. A procedure is authored here, and nothing anywhere holds that sequence until the record says so.

**This system owns every genesis.** It writes the plan, composes the procedure and opens the execution. A client outside can only move what the keeper created, which is the posture the whole context is arranged around and the thing that changed most recently: there used to be a Run aggregate whose genesis an outside reporter issued, so a client could bring a record into existence. See [What became of the Run aggregate](#what-became-of-the-run-aggregate).

The routine itself still runs outside, in whatever **engine** the deployment has. This context holds what that engine can be asked for, what it was asked for, and what it was reported to have done, never the running of it.

## What a Plan is

A plan is something this system can be asked to run, written down.

```
   Plan
     id                 a UUID minted at definition, never reused
     name               what the engine calls the routine
     parameters_schema  the shape a run of it must supply
```

Three fields. The name is not decoration: it is how the engine identifies what to run, so a plan without one names nothing and there is no act to record.

Two plans may share a name and nothing stops that. That follows from what the name is for rather than being a rule of its own. This system identifies a plan by its id everywhere it matters: a run cites an id, and `GET /plans/{plan_id}` reads one back. The name is the handle the engine uses, carried so this system can eventually say which routine to run, and a handle does not have to be unique to do that job.

One routine constrained two ways is two plans, and which one a run cites is what says how it was constrained. Be aware of how little of that difference the record can currently hold: the schema subset has no `items` keyword, so two plans that differ only in which devices they allow are the same document twice, distinguishable by id and nothing else.

## Why the schema is required

A plan carries a JSON Schema, in the constrained subset described in [Conventions](../reference/conventions.md#schema-validated-values), and it is required rather than optional.

The shared carrier-side validator accepts an absent schema and refuses the values that would have gone with it. A plan closes that case earlier, at definition. An operator with nothing to constrain declares a schema that constrains nothing and says so in the record; the alternative is a plan that can never refuse a parameter, with nothing saying whether that was meant.

So of the four cells in that posture table, the absent-schema row is unreachable from here. It stays in the shared helper because the helper is shared and the next declarer may want it.

## What a Procedure is

A procedure is a routine this system composed: an ordered list of steps, each naming what it touches.

```
   Procedure
     id        a UUID minted at definition, never reused
     name      what this system calls the routine
     beamline  where it runs, such as 2-bm
     steps     moves and acquisitions, in order, each under an id
               minted for it at definition
```

`beamline` is the routing key. The keeper dispatches an execution and something
at a beamline has to be able to ask for the ones it can drive, which means
"every dispatched execution at 2-bm" has to be a query rather than a read
of every procedure in turn. A dispatch copies it onto the execution, where
that query can reach it.

It is asserted, not derived. A procedure whose steps name `2bmb:m1` can
only run at 2-BM, so this states once what the device addresses already
imply, and parsing the prefix instead would mean this system owning a
grammar that belongs to whatever drives the procedure. It is checked
against nothing, for the reason a scope is: there is no Beamline
aggregate, and a second register of which beamlines exist would be a
thing to keep in step with the beamline descriptors
for no reader's benefit. A word nothing recognises is storable, and shows
up as a dispatch no conductor asks for rather than as a refusal here.

A step is named when it is composed, and that name is what an execution's step cites. Without it the only way to say which definition a step of a traversal came from is its position in two lists. `GET /procedures/{procedure_id}` returns the ids, which is what makes the join something a caller can actually make.

Two kinds of step, and only one of them declares what it touches.

```
   Move      record, to           what it touches is the record it names
   Acquire   plan_id, parameters, scopes
```

A move sends one record to one value, so deriving what it touches is exact and a declared field would be a second chance to say the same thing differently. An acquisition hands a routine to an engine, and nothing here can see inside that routine to work out which devices it will drive. So an acquisition declares its scopes and a move does not have the option, which is not an inconsistency: one is derivable and the other is not.

An acquisition must declare at least one scope. A step that declared none would be one this system believes touches no hardware, and that belief is what lets two of them run at once over one motor.

### What a scope is, and what this system does with it

Nothing. A scope is stored as the string it arrived as, and is not parsed into a namespace and a flag. Whatever drives the procedure owns that grammar, the overlap arithmetic runs in that process against its own ledger, and a second implementation here would be two things to keep in step for no reader's benefit. What is checked is that a scope is a non-empty string within a bound, which is what makes it storable.

### Where the parameters are checked

An acquisition's parameters are validated against the schema its plan declares, and the check runs at definition rather than when the procedure is walked. That is earlier and cheaper: a procedure with a malformed acquisition is refused before anything is dispatched, instead of failing partway through a traversal that has already moved motors.

Two gaps in that check are worth stating rather than discovering. An acquisition supplying no parameters at all is accepted whatever its plan requires, because the shared validator defers `required` to the point the values are finally acted on, which is the engine. And a plan retired or redefined after the fact does not invalidate a procedure citing it: the parameters were checked against the schema as it stood, and the record is a record of what was composed.

## What became of the Run aggregate

There was a fourth aggregate here: a Run, one carrying-out of one plan, opened by a reporter telling this system that an engine had run something. It is gone, and the collapse is worth reading before the rest of this page, because several sections below are shorter than they were because of it.

**A run and one acquisition step were the same fact in two vocabularies.** A run cited a plan and carried the parameters it was given. An acquisition step cites a plan and carries the parameters it was dispatched with. The only thing a run held beyond that was the engine's own name for it, and that now sits on the step as `engine_reference`.

The duplication only became visible when Procedure and Execution arrived. Before them, a run was the only record of anything having happened, and a step was a conductor's internal business this system never saw. Once the keeper composed the work and dispatched it, every step passed through here in the keeper's own vocabulary, and a run was a second record of the same act at a coarser scale.

**The collapse went this direction because most steps are not acquisitions.** A move drives a motor and opens nothing in any engine, so recording an execution as a run would have lost every step that was not an acquisition, which is most of them. There is no corresponding loss in the other direction.

**What did not collapse is the lifecycle.** A run had five statuses and a step has an outcome, and they are not the same observation: the outcome is what the driver saw when the call returned, and the lifecycle is what the engine said about itself. So a step carries both, and they are allowed to disagree. See [Two observers of one step, kept apart](#two-observers-of-one-step-kept-apart).

**What was dropped is the hand-run scan.** A run reported with no keeper reference used to be recorded. There is nothing here to record it against now: no execution, no step, and no way to make one out of a report. That is a real loss, chosen because it is reversible. Nothing is destroyed, the engine keeps its own record, and a reported shape can be added later as a purely additive change.

**Two things came free.** The standing hole where two runs could name one engine run closed by construction, because nothing outside opens a record any more. And a Walk's `reference`, which existed because a driver had no handle before starting, disappeared: this system creates the record first, so the execution's id is the handle.

## The fourteen operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Define a plan | `POST /plans` | `define_plan` | `201` with the new id |
| Read one back | `GET /plans/{plan_id}` | `get_plan` | `200` with the plan |
| Find plans | `GET /plans` | `list_plans` | `200` with a page of plans |
| Define a procedure | `POST /procedures` | `define_procedure` | `201` with the new id |
| Read one back | `GET /procedures/{procedure_id}` | `get_procedure` | `200` with the procedure and its steps |
| Find procedures | `GET /procedures` | `list_procedures` | `200` with a page of procedures |
| Dispatch an execution | `POST /executions` | `dispatch_execution` | `201` with the new id |
| Something took it up | `POST /executions/{execution_id}/claim` | `claim_execution` | `204` |
| One of its steps ended | `POST /executions/{execution_id}/steps` | `report_step` | `204` |
| An engine moved a step's run | `POST /executions/{execution_id}/steps/{step_id}/run` | `report_step_run` | `204` |
| Nothing more is coming | `POST /executions/{execution_id}/end` | `end_execution` | `204` |
| Read one back | `GET /executions/{execution_id}` | `get_execution` | `200` with the execution and its steps |
| Find executions | `GET /executions` | `list_executions` | `200` with a page of executions |

All fourteen are published twice, once as an HTTP route and once as an MCP tool, from the same handler. The status codes are declared once, in `apps/keeper/src/keeper/execution/routes.py`.

The four operations that move an existing execution take an optional `occurred_at`. The three that mint a record do not: defining a plan, composing a procedure and dispatching an execution all happen here, at the moment the record is written, so there is no earlier instant for a caller to report. That split is R8's, and it is explained under [When a report says it happened](#when-a-report-says-it-happened) below.

The engine report is the odd endpoint: a step in the path and the verb in the body, where every other transition here puts the verb in the path. The difference is what the caller is. A driver calls one endpoint per thing it means; a reporter drains an engine's document stream and turns each document into whichever of six it is, so a path per verb would make it build a URL by lookup where a field costs it nothing.

Both schemas and parameters come back exactly as they were stored, not re-rendered. A caller generating a form, validating a request locally, or comparing what an engine was given against what it asked for has to be working from the record rather than from a rendering of it.

## What the streams hold

There is no plans table and no executions table. Current state is recomputed by replaying a stream on every read.

There are three derived tables, one per aggregate, and none holds state the fold does not. See [Finding one without its id](#finding-one-without-its-id).

```
   PlanDefined        plan_id, plan_name, parameters_schema, occurred_at

   ProcedureDefined   procedure_id, procedure_name, steps, occurred_at

   ExecutionDispatched  execution_id, procedure_id, procedure_name,
                        steps, occurred_at
   ExecutionClaimed     execution_id, occurred_at
   ExecutionStepDone    execution_id, index, engine_reference, occurred_at
   ExecutionStepRefused execution_id, index, occurred_at
   ExecutionStepBroken  execution_id, index, cause, occurred_at
   ExecutionStepSkipped execution_id, index, occurred_at
   ExecutionStepEngine*    execution_id, step_id, engine_reference, occurred_at
   ExecutionEnded       execution_id, occurred_at
```

`ExecutionStepEngine*` stands for six classes, one per thing an engine can be reported to have done: started, paused, resumed, completed, aborted, failed. Six classes and not one carrying a verb, because an event in a log nobody can edit should not need reading twice, and the command that produces them does carry the verb, because a command is refusable and an event is not.

A step outcome is addressed by index and an engine report by step id, which looks inconsistent and is not. A driver walks the list it was handed and knows where it is; whatever watches an engine knows only the id a driver carried into that engine's metadata.

One event on a plan and one on a procedure, because nothing changes either yet. Retiring one arrives as a new class when the command that does lands, never as a field edited onto the genesis.

A procedure's whole step list rides its genesis, as a list of objects rather than flat fields, which makes it the only payload here holding a nested structure. Each step carries a `kind` discriminating a move from an acquisition. That key is on the wire and not on either class in the model, because there the class IS the kind and a field saying so again is a second thing to get wrong.

Every event after the genesis carries the same two fields. What is running is already on the stream, so a later event adds when, and which thing happened, and nothing else.

Neither the pause nor the resume says why. A pause raised by a signal, by an operator, and by the routine asking for one itself all arrive as the same fact, because stopped versus not is the distinction this system can act on and the rest is the engine's to keep.

The plan's name rides the payload as `plan_name` rather than `name`. The personal-data check reads field names and cannot tell a routine's name from a person's, and an unqualified `name` on an append-only row is the shape that rule exists to stop. The state keeps the bare `name`, where the aggregate it hangs off already supplies the qualifier.

A dispatched step travels as three fields: its id, the sentence rendered for a reader, and the plan it runs. The sentence is for display and the plan is what anything outside reads, which is why both are there when one of them contains the other as text.

## The state machine

An execution has one, and so does the run an engine opens for one of its acquisition steps. They are two machines on one stream, and keeping them apart is the whole of the section below on two observers.

```
        dispatch_execution
                │
                ▼
         ┌────────────┐  claim_execution  ┌─────────┐
         │ Dispatched │ ────────────────► │ Claimed │
         └────────────┘                   └────┬────┘
                                               │  a step, or an engine
                                               │  report, is relayed
                                               ▼
                                          ┌─────────┐
                                          │ Running │
                                          └────┬────┘
                                               │  end_execution
                                               ▼
                                          ┌─────────┐
                                          │  Ended  │
                                          └─────────┘

   a second claim, from any status               refused, 409
   anything at all after Ended                   refused, 409
   a step reported twice                         refused, 409
```

Three live statuses and one terminal. `Dispatched` is the first genuine transient in this tree, and it is one on purpose: an execution exists from the instant it is handed out, and nothing is driving it until something says so. Everywhere else in this repository there is no moment where a command has arrived and its event has not, because a handler decides and appends in one call. That stops being true the moment this system dispatches.

A second claim is what two drivers believing they own one traversal looks like, and refusing it is what makes the disagreement visible. Nothing here can stop the second driver moving a motor; what it can do is refuse to record that the execution was taken up twice.

`Dispatched` standing for a week says nothing was ever claimed. It does not say the dispatch failed, and telling those apart needs something watching the clock rather than another value. An execution whose driver died partway shows as `Running` with fewer steps reported than it holds, and stays that way.

`status` is not stored. The fold derives it from which events the stream carries, so it cannot disagree with the history behind it.

### The engine's own machine, one scale down

```
                report Started
                      │
                      ▼
               ┌───────────┐   report Paused   ┌────────┐
               │  Running  │ ────────────────► │ Paused │
               │           │ ◄──────────────── │        │
               └─────┬─────┘   report Resumed  └───┬────┘
                     │                             │
                     └──────────────┬──────────────┘
                                    │
              Completed        Aborted          Failed
                     │              │                │
                     ▼              ▼                ▼
               ┌───────────┐  ┌─────────┐      ┌────────┐
               │ Completed │  │ Aborted │      │ Failed │
               └───────────┘  └─────────┘      └────────┘

   a report that does not follow the one before it   refused, 409
```

Five states and six reports, and the extra report is the reason they are separate types. A resume puts the run back into `Running`, so a caller sending the state alone would be saying the same word for opening a run and for carrying one on, and this system would have to infer which from what it already held.

All three endings are reachable from `Paused` as well as from `Running`, which is the edge most easily got wrong. A paused engine is exactly the one an operator aborts.

Three terminals rather than one with a reason beside it, because the engines this system is built to hear from report exactly these three, and a reader should not have to parse a string to recover a distinction the source already drew. They split by who or what ended the run: itself, someone else, or a fault.

Nothing carries a reason. A free-text reason is the field most likely to end up holding something about a person, in the one table that cannot be edited, and an engine's failure message is exactly that kind of text. `ActorDeactivated` carries none for the same reason.

A report that does not follow is a 409 and not a 400, and that correction was made for the caller this endpoint exists for. A reporter draining a document stream re-sends the same stop after any restart, so a redelivery is the expected case; as a 400 it was indistinguishable from the reporter sending something malformed, which is the difference between an outcome to move past and an alert.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidPlanNameError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidPlanParametersSchemaError` | 400 | Not a Draft 2020-12 document, or outside the stored subset. |
| `InvalidProcedureNameError` | 400 | Empty after trimming, or over the length bound. |
| `InvalidProcedureStepsError` | 400 | No steps, too many, a move naming no record or sent to a value JSON cannot carry, or an acquisition declaring no devices. |
| `InvalidProcedureParametersError` | 400 | An acquisition's parameters do not satisfy the plan it cites. Names which step. |
| `InvalidExecutionProcedureNameError` | 400 | The procedure's name falls outside what an execution stores. |
| `InvalidExecutionStepsError` | 400 | The rendered step list is empty, too long, or holds a blank step. |
| `InvalidStepReportError` | 400 | A step report carried a detail belonging to a different outcome, or a break named no cause. |
| `InvalidIdentifierError` | 400 | An external reference had an empty or over-long half. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `PlanNotFoundError` | 404 | The id names no plan, whether the caller asked to read one or cited one in a procedure. |
| `ProcedureNotFoundError` | 404 | The id names no procedure, or a dispatch cited one that does not exist. |
| `ExecutionNotFoundError` | 404 | The id names no execution. |
| `ExecutionStepOutOfRangeError` | 404 | The index is past the end of the list the genesis fixed. |
| `ExecutionStepNotFoundError` | 404 | The same mistake made by id rather than by index. |
| `PlanAlreadyExistsError` | 409 | Definition was aimed at an id that already has a history. |
| `ProcedureAlreadyExistsError` | 409 | The same, for a procedure. |
| `ExecutionAlreadyExistsError` | 409 | The same, for a dispatch. |
| `ExecutionCannotBeClaimedError` | 409 | The execution is not waiting to be taken up: something already claimed it, or it ended. Carries the status. |
| `ExecutionAlreadyEndedError` | 409 | A close arrived for an execution that had already closed. |
| `ExecutionStepAlreadyReportedError` | 409 | That step already has an outcome, and a step ends exactly once. |
| `StepRunCannotBeReportedError` | 409 | The engine report does not follow the engine state already recorded. Carries both. |
| `ConcurrencyError` | 409 | The execution changed between the read and the write. Reload and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

One table, where there were two. The second existed because the execution refusals had been left out of the first and adding them in place would have buried the distinction between an aggregate this system is told about and one it drives. Every aggregate here is now one this system drives, so there is one kind of record and one table.

`InvalidIdentifierError` is the odd one. It belongs to a shared value object rather than to an aggregate, so it does not follow the naming shape the other three do and is not defined in a state module. Nothing else registers a status for it, and unregistered it would be a 500.

`StepRunCannotBeReportedError` is one class covering a whole state machine, which is where this parts company with the Run aggregate it replaced. A run's five transitions were five slices and so five errors, each named for the verb its caller called, and R6 is about not collapsing several VERBS into one class. This is one slice taking a discriminator, so the verb is a value rather than a call site, and five classes would be five names for one refusal nobody could tell apart by type. The error carries the state it holds and the report it got.

`ExecutionCannotBeClaimedError` carries the status for the same reason: being told an execution cannot be claimed is much less useful than being told something already claimed it, which is a contest, or that it ended, which is merely late.

A plan that is not there and a plan that refuses the values are deliberately different statuses. One means fix the id, the other means fix the values, and a caller needs to tell them apart.

Names and references are checked twice on the HTTP path, and the two checks answer to different callers. One the request model can refuse never reaches a command and gets FastAPI's own 422; one it cannot, such as a string of spaces, is refused by the value object inside the decision function and gets 400. Neither covers the other's callers, because the MCP surface has no request model.

Reading is gated like writing. A plan says what this system can be asked to run and what a request has to look like; a procedure says what it was asked to do and to which devices; an execution says what happened. All three are things a deployment should get to decide who may see.

## When a report says it happened

The four commands that move an existing execution accept an optional `occurred_at`, and a caller who omits it gets the moment their report arrived.

This matters most where it is easiest to overlook. For a driver reporting live, the gap between when a step ended and when this system heard is milliseconds. For a reporter that was down for an hour it is an hour. For a backfill out of an engine's own archive it is years, and without this field every one of those would be recorded as having happened on the afternoon somebody ran the import.

**Which commands take the field is itself the claim.** The three that mint a record do not, and the asymmetry is the point. Defining a plan, composing a procedure and dispatching an execution are acts this system performs: the moment it writes one is the moment it exists. A step being driven and an engine opening a run for it happened somewhere else. That is R8 in [Naming](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one), and the split now runs through one aggregate rather than between two.

A supplied timestamp must carry an offset and is stored as UTC. It is not checked against anything else: not against the clock, not against the execution's own genesis. A step may therefore claim to have finished before the execution was dispatched.

That is not laxness, it is the same posture the rest of this context takes. An engine's `exit_status` is not second-guessed either. What is promised is that the record says plainly what was claimed, and separately says when it was written down, and the second of those is written by the database rather than by this application, so no caller can touch it. See the Time section in [Conventions](../reference/conventions.md#time) for the full reasoning.

A list row carries both timestamps and a single read carries neither, which is a decision on each side rather than an oversight on one. A list is read to find something, and when an execution ran is how a person recognises the one they meant. A single read already names it, so the question is answered before the timestamps could help.

## Finding one without its id

Three reads in this context name what they want. `GET /plans/{plan_id}`, `GET /procedures/{procedure_id}` and `GET /executions/{execution_id}` replay one stream each and answer from it, which costs one query and stays correct forever because the stream is the record.

Four questions cannot be answered that way: which plans answer to a name, which procedures do, which executions were dispatched for one procedure, and which are waiting at one beamline. Answering any of them would mean replaying every stream of its kind to see which ones match. A fold needs to know which stream to fold, and that is exactly what is being asked.

So there is a second read path:

```
   POST /plans                      GET /plans/{plan_id}
   POST /procedures                 GET /procedures/{procedure_id}
   POST /executions                 GET /executions/{execution_id}
     |                                fold a stream each. Unchanged.
     | event
     v
   events  (the record)             GET /plans?name=...
     |                              GET /procedures?name=...
     | one worker, three bookmarks  GET /executions?procedure_id=...
     v                                read the tables below
   proj_execution_plan_summary
   proj_execution_procedure_summary
   proj_execution_execution_summary
```

Three things about it are worth knowing before reading a row.

**It lags.** `POST /executions` returns before the row exists. Normally tens of milliseconds, never zero. A caller that writes and immediately lists may not see what it just wrote.

**It can be thrown away.** Every column is derived from the event log, so dropping the table and resetting its bookmark to zero rebuilds it exactly. The log is the record; this is a convenience over it. That is why these tables take full `UPDATE` and `DELETE` while `events` does not.

**It is not a second way to write.** Nothing but the worker writes a row. A handler that wrote one directly would be inventing a fact the log does not hold.

There is a port per aggregate, each declared with the aggregate it summarises, and two implementations of each. A deployment reads the table. An environment with no database folds every stream of that kind instead, which is the expensive thing the table exists to avoid and is free when the whole store is a dictionary. A shared contract suite per port runs against both of its sides, because the two sides share no code and the claim that they answer alike is otherwise just prose.

**The procedure index is not unique, and that is the ordinary case.** A routine composed once is executed every time it runs, so many executions under one procedure is what a deployment looks like rather than a duplicate. A unique constraint there would refuse the second run of anything.

**A plan name is where the questions differ.** A plan's name is not an identity: it is the engine's handle, and this system holds plans for every engine it hears from. So `GET /plans?name=count` returns however many there are, and it is a way to see them rather than a way to choose between them.

Choosing is the caller's, and a caller that has to choose holds a mapping rather than applies a rule. Something composing procedures for one engine knows which installation it serves and which plan each name means there; this system knows neither, and nothing on the two records would tell it apart if it tried. A lookup returning one of two would be making that choice on every call, silently, on the strength of an ordering nobody asked about.

## What an Execution is

An execution is one traversal of a procedure: the record this system opens when it dispatches one, and how far the thing driving it got.

```
   Execution
     id              a UUID minted when the record is written
     procedure_id    the routine that was dispatched
     procedure_name  its name, copied at dispatch
     beamline        where it runs, copied at dispatch
     steps           each with its own id: what it was asked to
                     perform, and how each ended
     status          Dispatched, Claimed, Running or Ended
```

`beamline` is the one field here that exists for a query rather than for
a reader. A conductor asks for every dispatched execution at its own
beamline, which is a filter over many rows, so the value has to be on the
row rather than one reference away. That is what separates it from the
plan id a step used to copy: that answered one reader's question about
one row with the whole definition a hop away, and this selects the page.

Each step carries an id of its own, minted at dispatch and written onto the genesis. It is on the payload rather than made during the fold because a fold has to produce the same steps on every replay, and a record other aggregates point at cannot move between them.

A step has an id at all so that something outside can name one. A dataset is produced by one acquisition, not by a whole traversal, so `(execution_id, index)` would be a pointer into the interior of another aggregate rather than a handle: it cannot be fetched, and checking it exists means folding the whole execution and bounds-checking an integer. Both [Custody](custody.md) and [Counsel](counsel.md) now cite one.

**A step also cites the composed step it came from**, and that arrived with the second consumer rather than the first. Custody only needed a step to exist, so an id was enough. Counsel needs to ask something about one, whether it ran the plan a proposal named, and nothing on the record could answer: the plan id was present only inside the rendered sentence, written for a person to read.

```
   Procedure R1                    Execution E1, on Tuesday
     T1  move 2bmb:m1 to 0.0  <------  S1  from T1
     T2  acquire plan P1      <------  S2  from T2
           exposure 0.25
           touches 2bmb:det:         Execution E2, on Wednesday
                            <------  S3  from T1
                            <------  S4  from T2
```

Two ids on one step, and they are not interchangeable. `S2` names this traversal's step, which is what Custody and Counsel point at, and `T2` names the definition every traversal of the procedure shares. They cannot be collapsed, because one procedure is dispatched many times.

**The first shape of this copied the plan id onto the step instead.** It worked and it was replaced, because a copy answers one consumer's one question and the next question needs the next field, a payload key and a migration each. A citation answers all of them: the plan, the parameters the step was composed with, and the devices it declares are all on the definition. The alternative to both was a positional join against the procedure's own step list, built by one zip in one decider and asserted nowhere.

Rot is what a copy would buy, and there is none to buy. A procedure has one event and nothing edits it, so a citation that resolved once resolves forever, and changing a routine means composing another one.

An execution cites its procedure and still copies its name and its steps' descriptions. That copy is not redundancy. The fold is pure and cannot load another stream, so the length of the step list has to ride the genesis for the outcomes to have anywhere to land, and once the count is there the sentences cost one string each and keep the record readable on its own.

### Why an execution has a status when nothing else here does

Every other aggregate in this repository is free of transient states, because there is no moment where a command has arrived and its event has not. That holds for a record of something somebody else did. It stops holding the moment this system dispatches.

Dispatching means waiting. An execution exists from the instant it is handed out, and nothing is driving it until something says so.

```
   dispatch_execution
        │
        ▼
   ┌────────────┐  claim_execution   ┌─────────┐  report_step  ┌─────────┐
   │ Dispatched │ ────────────► │ Claimed │ ────────────► │ Running │
   └─────┬──────┘               └────┬────┘               └────┬────┘
         │                           │                         │
         │ report_step               │                         │
         └───────────────────────────┴────────────┬────────────┘
                                                  │
                                              end_execution
                                                  │
                                                  ▼
                                            ┌──────────┐
                                            │  Ended   │
                                            └──────────┘

   claim_execution from anything but Dispatched    refused, 409
```

`Dispatched` is the first genuine transient in this tree, and it is one on purpose. A row sitting there with an old timestamp says nothing ever took the work up, which is a different failure from a driver that died partway: that one reads as `Running` with steps unreported. Nothing here can tell either from something merely slow, which is the limit Conducting names rather than papers over.

Claiming is refused from every status but `Dispatched`, which makes it the only command on this stream that refuses from a live status as well as the terminal one. A second claim is two drivers each believing they own one traversal. Nothing here can stop the second from moving a motor; what it can do is refuse to record that the execution was taken up twice, so the disagreement ends up in the log rather than only at the beamline.

Claiming is not a gate on reporting. A driver that reports a step without claiming first moves the execution straight from `Dispatched` to `Running`, and that is allowed: a claim says who has the work, and refusing the report would lose a fact this system was told in order to enforce an ordering the log does not have.

### No reference of its own

An earlier shape had the driver mint a name for the execution before its first step, because at that moment there was no handle to refer to. Under a dispatch there is: this system creates the record first, so the execution's id is the handle, and it is the id a driver carries into whatever it asks an engine to run.

Each step ends exactly once, in one of four ways:

```
   Done      the seam returned, which is not the same as the step working
   Refused   a claim conflict stopped it before it touched anything
   Broken    the seam raised
   Skipped   the execution had already stopped before reaching it
```

### Two observers of one step, kept apart

An acquisition step gets talked about twice, by two clients that do not know about each other.

```
   outcome        what the driver saw     Done, Refused, Broken, Skipped
   engine_state   what the engine said    Running, Paused, Completed, Aborted, Failed
```

They are two fields because they can disagree, and the disagreement is the point. A spike drove four collisions into a real scan and every one of them ended `exit_status: "success"`, so neither observer is reliable and collapsing the two would make this system pick a winner between claims it cannot check. A step whose call returned while its engine reported a failure reads as `Done` and `Failed`, which is the honest record.

A move carries no engine state at all, because a move opens no run for anything to watch.

The five engine values are deliberately the five a run has. It is the same engine reporting the same lifecycle one scale down, and a reader who has learned one should not have to learn a second vocabulary for it. The transitions are the same too: all three endings are reachable from `Paused` as well as from `Running`, a resume is the only edge pointing backwards, and nothing follows an ending.

Neither account waits for the other. A driver may report its call returning before or after the engine reports the run ending, so requiring an order would refuse whichever arrived first. An engine's account is accepted even after an execution has been closed, because a driver that gave up does not stop the hardware from having done something, and that account is the only record of what it did.

`Done` is the word most likely to be read as more than it is. Every corrupted scan in a spike came back reporting success, so the outcome says the call returned and nothing about whether the science worked. `Refused` is the only unambiguously good news in the set.

An outcome carries at most one detail, and two of the four carry none. A done step may name the run it opened and a broken step names the class that was raised. A refused step names nothing, and a skipped step never could.

That a refusal says nothing about the conflict is a boundary rather than a gap. Which step was holding the device, and which scopes collided, are facts about a ledger that lives in the driver's own process and is not durable by its own argument. Nothing here can act on either, and an append-only table is the wrong home for another process's working notes. A driver that wants to explain a refusal to a person has the ledger in front of it.

There is no value meaning abandoned. An execution whose driver died reads as `Running` with steps unreported and stays that way, because saying more needs something watching rather than another status.

`GET /executions/{execution_id}` is the only read that returns the steps. A listing drops them, because up to a thousand of them per execution would make a page of fifty almost entirely steps, and what a list needs instead is how far the execution got. On a listing that is `reported_count` against `step_count`, beside `status`, which separates the cases a reader has: never taken up, taken up and not started, running, closed having reported everything, and closed having not.

On a read, a step nothing has reported carries a null outcome, which is a different fact from `Skipped`. Skipped means the execution reached that step and passed it over; null means nothing was ever said about it.

## Why the execution summary holds a set and not a counter

Every other projection in this repository writes absolute values, so a replayed batch is harmless by construction: a status derived from an event type is the same value however many times it is written. Progress through an execution is not a value of that kind.

Delivery into a projection is at-least-once, because the worker advances its bookmark in the same transaction as the writes and a crash between the two replays the batch. A column incremented per step would count a replayed step twice and report an execution further along than it is, which is the one lie a record of an abandoned execution must not tell.

So the row holds the set of step indices reported and each step event unions one into it. A union is idempotent where an increment is not, and the count a caller reads is the size of the set.

## The one query expected to run continuously

`GET /executions?beamline=2-bm&status=Dispatched` is how something at a beamline finds work the keeper has dispatched and nothing has taken up. It is the only read here that a machine makes on a loop rather than a person makes on a question, which is why `(beamline, status)` carries an index of its own and why both halves are on the summary row rather than one reference away.

Both filters are needed and neither is enough. A beamline alone returns work already being driven; a status alone returns three other beamlines' work. Claiming either by mistake would mean a conductor driving hardware it does not own, and a claim is a write with no command to take it back.

**The request can be held open.** `wait` turns the query into a long poll: rather than answering an empty page, the keeper holds the request until a dispatch appears for that beamline or the wait runs out. An idle conductor then sits on one open connection and re-opens it every thirty seconds, instead of asking every few seconds and almost always being told nothing, and work reaches it in milliseconds rather than at the next tick.

The bound is a socket keepalive ceiling and not a latency budget. A connection held indefinitely dies in a proxy or a NAT table without telling either end, so the request returns empty at the ceiling and the caller opens another. A dispatch landing in that gap is not lost: it is sitting at `Dispatched`, and the next request returns it.

What wakes a held request is a Postgres `NOTIFY` fired by a trigger on the summary table, not the one on `events` that the projection worker listens to. An event landing is not yet a row this query can answer from, and a request woken by that one would find the worker still mid-transaction. `dispatch_signal.py` holds the argument.

The signal is a latency optimization and never the answer. A notify can arrive while nothing is listening, or between a reader's query and its next wait, so each wait inside a held request is itself bounded and the query runs again after it. A missed signal costs a slower pickup, never a dispatch nobody takes up.

The answer is a page and not a single execution, and nothing reserves a row for the asker. Two conductors reading the same page is expected, and what keeps them apart is the claim: `POST /executions/{execution_id}/claim` is refused from every status but `DISPATCHED`, so the second one gets a 409 and moves on. The mutual exclusion is the event store's optimistic concurrency rather than anything this query does.

## An execution cannot check the engine run its step opened

A procedure's genesis checks that every plan it cites exists, and that check is real. The equivalent one scale down is unavailable, and the reason is worth stating rather than discovering.

A driver reports an acquisition step the moment its engine returns, and carries the engine's own name for the run it opened. Nothing here can ask that engine whether such a run exists, and nothing holds a record of it to check against: the run record this context used to keep is exactly what was retired. So `engine_reference` is a correlation hint rather than a key, which is what `docs/reference/client-contract.md` already says such a reference is.

That is weaker than a plan reference and it is the honest shape. An engine's names are the engine's, and a system that claimed to have checked one would be claiming to have asked.

## Why the three share a context

An acquisition step cannot be composed without the plan it cites, and checking one against the other is the whole of what a procedure's genesis does. A dispatch cannot open a record without copying the procedure it hands out. Across a context boundary each of those would have to reach through a sibling's read-side surface for a relationship neither side can be without, so the three stay together.

## This system owns every genesis

The context used to be **reported**: an engine ran a routine, and afterwards someone or something told this system that it did. It is now **dispatched**: this system composes the work and hands it out, and what comes back is how it went.

That is one sentence and it changed more than any other decision recorded on this page. Under the reported posture a client could bring a record into existence, which is why two runs could name one engine run and why the context needed a whole section arguing about what to do with the duplicate. Under this one there is nothing for an outside caller to create.

What still comes from outside is how the work went, on two channels that can disagree, and neither is treated as the other's correction. That is the section above on two observers.

**Reported is still the right word for those two channels**, and deliberately not witnessed, which was the first word here. To witness something is to have been present and able to vouch for it. This system is neither: it is told, and the whole of what it knows is that it was told. The caller could be wrong and nothing here can check. "Witnessed" would claim otherwise, and this tree refuses unbacked claims everywhere else.

### Why the verbs are bare imperatives

The commands say `claim_execution`, `report_step`, `report_step_run` and `end_execution`, and the mixture is deliberate.

Two of them name the act plainly, because it is an act: claiming an execution and ending one are things a caller does here, and the record is made by the doing.

The other two are reports, and say so. Read as instructions, they would be addressed to something this system cannot instruct. Nobody asks a step to break. What a caller is asking is for the record to say what already happened, and the request is refusable, which is what keeps it a command rather than an inbound event.

**A reserved table of driving verbs used to sit here**, pairing each reporting verb with the one a future driving surface would use: `report_run` against `start_run`, `pause_run` against `request_pause`. It is gone, and not because the question went away. It was answered differently. This system dispatches a whole procedure and a conductor carries it out step by step, so there is no `start_run` for this context to reserve a name for: the driving verb is `dispatch_execution`, it already exists, and it is the only one.

What a driving surface would still add is the asking side of a pause, which is a request to a conductor rather than a report about an engine. That belongs to the conductor's own intake, not here, and Conducting is where it is discussed.

## Where the code is

```
   apps/keeper/src/keeper/execution/
     aggregates/plan/           state, events, the fold, how to load one, and
                                the summary a list shows with the port over it
     aggregates/procedure/      the same, for a procedure, whose state module
                                also holds the two step kinds
     aggregates/execution/      the same, for an execution, whose state module
                                holds the step, both its observers and two enums
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the tables in step with the log,
                                and the call that hands them to the worker
     features/
       define_plan/             command, decision, handler, route, tool
       get_plan/                a query slice, so no decider: reading decides nothing
       list_plans/              the queries a fold cannot serve, one per
       define_procedure/        with a context module too, for the plans its
                                acquisitions cite, which is several
       get_procedure/           the only read that returns the typed steps
       list_procedures/         aggregate
       dispatch_execution/      with a context module, for the procedure it copies
       claim_execution/
       report_step/             one slice, four outcomes on a discriminator
       report_step_run/         one slice, six reports on a discriminator
       end_execution/
       get_execution/
       list_executions/
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

**Thirteen directories where there were twenty-one.** Eight left with the Run aggregate, and six of those were its transitions: five near-identical handlers plus a genesis. [Layout](../reference/layout.md#bc-root-extras) records a shared shell for them that was built and then reverted, and the decision it records is still the live one, because the same question came up again here and was answered the other way.

`report_step` and `report_step_run` each take a discriminator rather than splitting into four and six slices. That is the reverse of what Run did, and the reason is that the outcome is a value on a refusable command rather than a separate call site: one command that can be refused, several event classes that cannot be set wrong. Thirty near-identical files would have been the wrong trade when the sibling slice on the same stream had already answered it.

`define_procedure/context.py` carries more than one sibling, and is the only context module here that does. A procedure may acquire several times, so its handler loads each distinct plan once and hands the lot across keyed by id. Once, because a tomography procedure acquiring the same plan at twenty sample positions would otherwise replay that stream twenty times for no new information.

## What is not here yet

The conductor's work intake. Something has to claim a dispatched execution and drive it, and nothing does: `dispatch_execution` writes a record that waits. `apps/conductor` holds the library that carries out a procedure and has no loop that goes looking for one. That is the largest single missing piece and it is what `Dispatched` is waiting for.

The recording seam on that side is stale in three places at once and is being left alone until the loop is written, so that its signature is written against this surface rather than beside it.

Anything about a pause beyond the fact of it. How long an engine has held a step paused, how many times it has, and what it is waiting for are all answerable from the events and none of them is on the read model. The first caller that needs one is the right place to decide whether it belongs there or in a projection.

Any way to say that an engine run ended without saying how. The three terminals assume the engine knows which one happened and says so, and the first engine modelled does. A second one, driven in a spike, does not: it writes the same completion string whether the routine finished, the detector timed out or an operator stopped it, so the outcome exists only in a log nothing can read. Against that engine every step would be recorded `Completed`, including the failed ones, and "how many acquisitions failed last week" would be answered confidently and wrongly.

Not decided here, because there is no caller: nothing reports from such an engine today. What the decision would be is a fourth terminal meaning the run is over and the reporter cannot say more, which is the same refusal to overclaim that picked `report` over `witness` above. Worth settling before a second direction is built on this aggregate, because the conducted path doubles what a wrong terminal set costs.

Any way to hear from an engine that names its run only at the end. The engine reference arrives on the `Started` report and every later report is matched to a step by the id a driver carried into the engine's metadata, so the shape assumes a stream that opens with something identifiable. The first engine modelled does that. The second, driven in the same spike as the terminal question above, has nothing of the kind: its only per-scan identifier is the path of the file it writes, and that path is written by the routine that ends the scan.

```
   an engine that names its run at the start
     start(ref) ---> Started ---> Paused, Resumed ---> Completed
          ^ the reference exists here

   an engine that names it at the end
     start(?) ........................................ end(ref)
                                                          ^ and only here
```

This is less damaging than it was. The reference is a correlation hint rather than a key, so an engine that cannot supply one still has its step reported: what is lost is the ability to join that step to whatever the engine wrote. Recording the whole thing in one call is still not a variation on this shape.

A shared shell for near-identical update handlers. It was built for the Run aggregate's five, measured against the alternative and reverted; see [Layout](../reference/layout.md#bc-root-extras). There are fewer of them to share now, which is a reason the question has not come back rather than an answer to it.

Any way to say which plan named `count` is the one to use now. Deliberately unanswered here rather than deferred: a caller resolving a name knows which engine it is speaking to and this system does not, so the mapping belongs with the caller. What would change that is a second caller wanting the same answer for a different reason, at which point the question is a plan lifecycle and worth deciding on its own terms rather than as a lookup.

Anything about where a plan belongs. Nothing on a plan says which installation it was written for, so two plans named `count` for two engines are the same record twice, and "every plan for this installation" is a question nothing here can answer. Whatever composes procedures carries that scope in its own configuration, which holds until something inside this system needs it.

Anything a projection could answer beyond finding a record: how long executions take, how many steps broke last week, which procedure is dispatched most. The tables have the columns for none of those, and each is a column and a filter when somebody asks.

Any search over what a plan constrains. The schema is on the record and on no index, so "which plans take an exposure time" is a question nothing can answer without reading every one.
