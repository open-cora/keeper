# Counsel

Counsel is the bounded context of advice: what was put forward to run next and was it taken, and what somebody asked a thinker about one execution and what came back.

It holds two aggregates. The Proposal came first and has five operations on it; most of the argument about it is which of two neighbouring contexts each piece does NOT belong in. The Inquiry came second and has five, and the argument about it is mostly about where it stops: it records the asking and the answer, and nothing about the thinking.

**This page was written before the code and then corrected against it.** That is the reverse of every other page under this heading, and two things it claimed turned out to be wrong when the code was written: the cross-context door is seven names wide rather than two, and the refusals on a take needed a discriminator the design had not named. Both are fixed below. Where a sentence is still about something unbuilt, it says so.

**It was then corrected a third time, when the Inquiry landed.** That aggregate was designed in conversation and written against the design rather than the other way round, which is this page's habit; what the code found is noted in its sections below. The Proposal sections are unchanged by it.

**It was corrected a second time, when the shape of Execution changed.** A proposal used to cite the run that took it. Work is now composed in [Execution](execution.md) as a Procedure, dispatched whole, and driven step by step, so what takes a proposal is one acquisition step of one execution. The Run aggregate has since been retired outright. The sections below say the new shape and keep the arguments that survived it, which is most of them.

## What a Proposal is

A proposal is a run put forward by an agent, before anything has run it.

```
   Proposal
     id            a UUID minted when the record is written
     actor_id      the agent that put it forward
     plan_id       the plan it proposes running
     parameters    the values it proposes
     execution_id  the execution holding the step that took it, once one has
     step_id       that step
```

It cites a plan, it does not contain one, which is the same posture [Execution](execution.md) takes and for the same reason: the plan is a record over there, and a copy here would go stale the first time somebody defined a new one.

That makes a proposal and an acquisition step the same two fields, and the difference between them is that one happened.

```
   Proposal        plan_id, parameters   nothing has happened
   Acquire step    plan_id, parameters   dispatched, and something drove it
```

That is not a missing field, it is the whole distinction: a proposal is the one record in this tree that refers to no act at all.

**Two fields for the reference, and never one without the other.** A step is an entity inside the Execution aggregate rather than a stream of its own, so the step id alone names something no reader can fetch. The root comes first and the step qualifies it, which is the order [Custody](custody.md) reads in too. They are written by one event, so a record holding one of them is not one this system can produce.

## Adopting one, which is how advice becomes work

A proposal put forward and never acted on is where this context used to
stop. Adopting is the other end: somebody chooses the proposal, says where
it will run and what it may touch, and this system composes a one-step
procedure for it and dispatches an execution.

That execution is an ordinary dispatched execution, which is the whole
trick. A conductor polls for those already and knows nothing about
proposals, so adoption adds an entrance to the path that exists rather than
a path of its own. Nothing in `apps/conductor` changed for it.

### What a proposal does not say, and why the caller must

A proposal cites a plan and carries values. A procedure needs a name, a
beamline and, on an acquisition, the devices the step may touch. Two of
those three this system refuses to invent, and says so where it refuses
them:

```
   beamline   define_procedure: "nothing here can derive it. The steps
              imply it, in a prefix this system deliberately does not
              parse, so the composer states it."

   scopes     "an acquisition declaring no devices; nothing here can
              derive them from the plan, and a step believed to touch
              nothing is one that can run beside another over the same
              motor."
```

So both are arguments to the adoption. The tempting alternative is to read
them off the execution the proposal came from, through the inquiry that
produced it: same plan, same devices, same beamline, and exact rather than
guessed. It is still refused. Scopes are the bound that stops two steps
driving one motor, and a bound the system inferred is one nobody decided.

The third, the procedure's name, is taken from the plan. One proposal is
one run of one plan, so the routine composed for it is named after what it
runs, and a caller naming it would be naming something it did not compose.

### Three streams, one transaction

Adoption writes a procedure, an execution and the adoption itself. It
writes them in one append, all or nothing, and this is the first slice in
the tree to use `EventStore.append_streams`, whose own docstring had been
waiting for a consumer.

```
   +-----------------------------------------------------------+
   |  Procedure  proc-N   ProcedureDefined                      |
   |  Execution  exec-N   ExecutionDispatched                   |
   |  Proposal   prop-1   ProposalAdopted(exec-N, step-id)      |
   +-----------------------------------------------------------+
```

The failure it removes is specific. Two callers adopting one proposal both
fold the same open state and both decide a whole procedure and a whole
execution; the loser finds out only when the store rejects its
`expected_version`. Appended one at a time it would already have dispatched
by then, and a conductor polling that beamline would walk work no proposal
points at, for advice that was also about to run under the winner.

That is the one failure that happens between the writes rather than before
them, which makes it the only one that tests the transaction. Both of the
other refusals, an empty bound and a proposal that is no longer open, are
decided before anything is appended and would pass under either shape.
`tests/integration/test_adopting_a_proposal_is_atomic_postgres.py` carries
all three and says which is which.

### Why the slice lives in Counsel, and what that costs

Because the dependency cannot point the other way. Counsel may read
Execution and does; Execution knows nothing of Counsel and must not, so a
slice over there that loaded a proposal would be a cycle rather than an
edge.

The price is the only edge in this tree that reaches another context's
feature layer. Composing and dispatching are Execution's decisions and are
made by Execution's own deciders, which are pure functions this handler
calls; only the append moves. Going through their handlers instead would be
three appends, which is the window the slice exists to remove.

## Why the aggregate has a status now

This page used to say a proposal needed none, because `execution_id is
None` carried the whole of it, and that an enum would arrive at the third
state. Adoption is that third state.

```
   Open      nothing has come of this advice
   Adopted   this system chose it and committed work to it
   Taken     something outside ran it and said so
```

Derived in the fold from which event landed, never stored, which is
`InquiryStatus`'s arrangement next door and `ExecutionStatus`'s before it.

The read model spells the same three states out of two nullable timestamps
and no status column, because a word beside them would be one fact written
twice. That the two derivations agree is not visible in either, so the port
contract carries the case that separates them: a proposal closed by
adoption, where a reader testing `taken_at` first reports it Open and
passes everything else.

The filter is still `is_open`, and deliberately. Adding a status parameter
needs somebody who wants to ask which of the two closed a proposal, and
there is not one yet. That is a parameter and an index the day there is.

## Two words for one stream, and why neither is the other

### Taken, adopted, and the accepted spelling still held back

```
   ProposalMade       an actor put a run forward
   ProposalAccepted   reserved: a person says yes, and it may still never run
   ProposalAdopted    this system composed work for it and dispatched it
   ProposalTaken      something outside ran it and said so
```

Two of those four close a proposal and in ordinary English they are near
synonyms, so the distinction has to be said rather than assumed. It is not
the act, it is the author of the commitment. Adopting means somebody
weighed this proposal, chose it, chose where it would run and what it could
touch. Taking means nobody here did: a step exists that ran what was
proposed, and whoever composed the procedure holding it may never have read
the proposal at all.

`accepted` stays reserved through both. Approval by a person is a real
future event on this stream, distinct from adoption and prior to it,
because an operator can approve something that is then never adopted.

`naming.md` predicted this pair before either existed: a verb that
describes today may need to drive tomorrow, and the rule is to prefix the
driving side and leave the bare imperative to the one that reports. Adopt
drives, take reports.

## Why this is not a status on an Execution

A proposal looks like a step nothing has driven yet, and modelling it as one would save a context. Two things stop it.

**A step does not exist on its own.** It is an entity inside an execution, and an execution exists because a procedure was dispatched. So a proposal modelled as a step would need a procedure composed and handed out before anybody had agreed the work should happen, which is the wrong order: proposing is what comes before composing.

**A proposal nothing came of would be a step nobody drove.** Every count of how far an execution got would carry steps nobody intended to run. That is the failure the [output-of-record test](../reference/modeling.md#choosing-where-an-act-is-recorded) exists to prevent: the same act landing in two places, or in this case a non-act landing among acts.

The argument this replaced was aimed at the Run aggregate and was longer, because a run's required external reference and its five-valued status each gave a separate reason against folding a proposal into one. Neither bears on a step, and the two above are what remain.

## Why the aggregate is not called Decision

Decision is the word most people reach for, and it fails two tests.

`Decider` is chassis vocabulary. It is in the [Glossary](../reference/glossary.md), it names a module in every write slice, and a decision function is what each one holds. An aggregate called Decision makes someone write "the decider for the decision aggregate", which is R1's collision count doing its job.

The deeper objection is the same one that got "witnessed" thrown out of Execution. Deciding happened inside an agent, over data and weights this system never saw. What arrives here is the expressed choice, and naming the record after the cognition claims the cognition. A proposal is what this system can hold.

## Why the context is called Counsel

The context is named for what it keeps rather than for what happens elsewhere, which is the move [Custody](custody.md#why-this-is-not-called-provenance) made in choosing its own name over provenance.

Counsel is advice given, and it claims only that. It does not claim the advice was weighed here, or that it was good, or that anything came of it. It also keeps its meaning as the record grows: counsel taken, counsel withdrawn and counsel superseded are all counsel, and the word still fits on the day this system drives the engine itself, because the counsel stays the agent's and the driving is Execution's business.

Two words were rejected. **Direction** reads well until you remember that at a synchrotron a direction is a vector. **Initiative** covers both modes and also means a campaign, which is exactly the aggregate this context defers, so it collides with its own future sibling.

## Who may propose

Whoever authenticated. The principal must be an active Actor in [Access](access.md), and an actor there is a person, a service account or a background process, so a scientist putting a run forward and a piece of software doing it produce the same record.

That is deliberate rather than incidental. Which parties a deployment lets propose is [Authority's](../reference/glossary.md) question, answered by granting `MakeProposal` to some principals and not others, and a context that hard-coded an answer would be holding an opinion the rulebook exists to hold.

Two consequences follow, and neither is a defect.

**A person is less likely to close the loop.** The join is written by whoever dispatched the work and calls `take_proposal`, which software that proposed will do as a matter of course and a person walking to the beamline will not. Proposals from people therefore sit open more often, so any count of how many were acted on reads low wherever people use it.

**Nothing on the record says which kind proposed.** "Was this run human-directed or autonomous" is a real governance question at a facility and this system cannot currently answer it. The fix, if one is wanted, is a typed marker on the Actor rather than a field here: a kind copied onto every proposal is a second copy of a fact Access owns, which is the mistake [Custody](custody.md#why-it-holds-so-little) refused. Access holds no such marker today.

This page still says "agent" in places, and means the autonomous case specifically when it does. Where it describes what the record holds, it says actor.

## Why an agent is not an aggregate here

An agent is an Actor in [Access](access.md), and this context adds no second answer to the question of who somebody is. Custody's page already assumed that arrangement when it placed the provenance agent in Access, and splitting the answer across two contexts would make "who is this" a question with two homes.

The fact Access genuinely cannot hold is which version of the deciding software spoke, and Access refuses descriptive fields on purpose. That fact does not belong on an agent record either, because it is not true of the agent. It is true of the proposal. Execution already wrote the argument, about a plan's schema rather than an agent's version:

> The parameters are checked against the plan's schema when the record is written, and not again. Re-reading the plan later may find a different schema, which does not make the record wrong: it makes it a record of what was run.

An Agent aggregate earns its place when something needs to ask a question about an agent across proposals. Nothing does yet, and until then the version is a field on the genesis if it is anything.

## The four operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Put one forward | `POST /proposals` | `make_proposal` | `201` with the new id |
| Read one back | `GET /proposals/{proposal_id}` | `get_proposal` | `200` with the proposal |
| Record that an acquisition took it | `POST /proposals/{proposal_id}/take` | `take_proposal` | `204` |
| Adopt one, and dispatch the work | `POST /proposals/{proposal_id}/adopt` | `adopt_proposal` | `201` with the execution |
| Find them | `GET /proposals` | `list_proposals` | `200` with a page |

All four are published twice, once as an HTTP route and once as an MCP tool, from the same handler, with the status codes declared once in `apps/keeper/src/keeper/counsel/routes.py`.

The MCP surface is not incidental here. An agent holding this context's tools can read what plans exist, put a run forward, and later record what came of it, which is the first time the agent surface carries a conversation rather than a single call.

## Made, and why that verb takes no timestamp

The genesis is `make_proposal`, producing `ProposalMade`, and it does not accept an `occurred_at`. That is the opposite of its neighbour in Custody and it is the point.

Everything Execution and Custody record is **described**: a run happened in an engine, a dataset was written by a store, and this system was told afterwards. A proposal made through this system's own surface is not like that. Proposing is a speech act, and the call is where it was spoken. There is no earlier moment out in the world for the record to be late to, so the moment this system writes one is the moment it happened.

That is [R8](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one) landing on the makes side, the same side as `register_actor` and `define_plan`. `take_proposal` lands on the describes side and does accept a timestamp, because a step was driven at a moment nothing here was present for.

**One aggregate with one command of each kind is new in this tree.** Everywhere else the split runs between contexts. Here it runs between two commands on one stream, which makes this the clearest place the rule is visible, and the reason the genesis and the join read so differently in the table above.

An agent that decided elsewhere and tells this system afterwards is a second genesis when it arrives, `report_proposal` producing `ProposalReported`, carrying a timestamp. Two event classes rather than a flag on one, which is the structural move Execution made for [what it owns and what it is told](execution.md#this-system-owns-every-genesis) and for the same reason: a field can be set wrong and a class cannot.

## What the stream holds

There would be no proposals table. Current state is recomputed by replaying a stream on every read.

```
   ProposalMade   proposal_id, actor_id, plan_id, parameters, occurred_at
   ProposalTaken  proposal_id, execution_id, step_id, occurred_at
```

**`actor_id` is on the payload and not on the command.** The handler writes the authenticated principal into it, so the caller controls who it proposed as exactly as much as a caller of `register_actor` controls the new actor's id, which is not at all.

That duplicates the envelope's `principal_id` deliberately. The envelope is infrastructure, the fold never sees it, and "which agent advised this" is a domain question that should be answerable from the domain record rather than from the persistence wrapper around it. The cost is two sources that can disagree, since `principal_id` is null on anything written before the principal hook or by a backfill, and the payload field is the one the aggregate believes.

**`ProposalTaken` carries no actor, and the asymmetry is meant.** On the genesis the principal is the substance of the fact. On the join the caller is a messenger, and the fact of record is the acquisition.

Neither event carries a reason, a goal, or a rationale. An agent's rationale is unbounded free text that will eventually quote a person, and the events table cannot be edited: the application's role has no UPDATE, DELETE or TRUNCATE grant on it. `ActorDeactivated` carries no reason for the same reason, and so does every run transition.

## Two states, and why there is no status

```
   make_proposal
         |
         v
   +-----------+   take_proposal   +-----------+
   |   open    | ----------------> |   taken   |
   +-----------+                   +-----------+

   take_proposal on a proposal already taken   refused, 409
```

An execution derives a `status` in its fold because four values cannot be read off any one field. A proposal can: `execution_id is None` is the whole of it. A two-value enum beside a nullable field is duplicate information, which is what [R6](../reference/naming.md#r6-cannot-transition-errors-are-per-verb-not-collapsed) objects to when it refuses to collapse a verb into a payload string.

An enum arrives at the third state. Withdrawing and superseding are the two candidates, and the first of them to land is what stops the answer being readable off one field.

Open is the honest default and stays honest the way Dispatched does. It says only that nothing has been recorded against this proposal. A proposal nobody acted on reads as open forever, and closing that needs something watching rather than another value.

**Taking one twice is refused, and that is a domain claim rather than a safety rail.** A rerun after a failure is a new proposal, because the second run was chosen after seeing the first one fail, and that is a second choice. Refusing is also the reversible direction: allowing it later costs a sentence, and disallowing it later costs a migration.

## Who writes the join

This is the part with a real gap in it, and the page is the right place to say where the gap is.

```
   agent      make_proposal(plan_id, parameters)        ->  P, open
                   |
                   | somebody decides to run it
                   v
   agent      define_procedure(steps=[..., acquire P's plan, ...])
              dispatch_execution(procedure_id)          ->  E, with step S
                   |
                   | a conductor claims E and drives it
                   v
              take_proposal(P, execution_id=E, step_id=S)
```

**The gap moved and did not close.** It used to be that nobody knew P caused the run except the agent, because the reporter drained an engine's documents and had never heard of a proposal. Now the ids are all minted here and the dispatch hands E straight back, so there is nothing to resolve by external reference and nothing to guess. What is still missing is the arrow in the middle: **nothing turns a proposal into a procedure.** Composing one is a separate call that a caller makes, and no record says it was made because of P until the take says so afterwards.

That is deliberate for now rather than overlooked. A proposal names a plan and its values, and a procedure is an ordered list of steps with moves between them, so turning one into the other is a composition decision rather than a translation. Whoever makes that decision is the open question, and it is the same question the conducting notes leave open.

Two consequences, and the list is shorter than it was.

**An open proposal can be stale by the length of one call.** The proposal summary projection lags by tens of milliseconds, and the caller's own dispatch-then-take lags by however long the execution takes. A list of open proposals will show some that are already being driven.

**A caller can name the wrong step.** One procedure is dispatched many times, so an execution id resolved from the wrong dispatch is an easy mistake, and a step id from one execution paired with another execution's id is easier still.

That is what the cross-record checks are for. The handler refuses an execution that is not there and a step that execution does not hold, then follows that step to the composed step of the procedure it was dispatched from, and `take_proposal` compares the plan that composed step runs against the proposal's and refuses a mismatch, because an acquisition of a different plan is not this proposal being taken at all.

The plan is read off the procedure rather than off the execution, and that is the third read this slice makes. An execution's step says what it was asked to do by citing its definition, not by copying pieces of it, so the question "which plan did this step run" is answered where the answer lives. See [Execution](execution.md#what-an-execution-is).

It does not compare parameters, and that is now a limit of the record rather than a choice. An execution copies each step's rendered description and the plan it runs; what it was dispatched with stays on the procedure. So there is nothing here to compare against, and there would be little point if there were: an engine normalizes values and fills defaults, so a dict comparison would refuse legitimate joins to catch a case nobody has seen.

**A step can also be a move, which a run could never be.** A move runs no plan, so it cannot have run this one, and the refusal says exactly that rather than reporting a plan mismatch against nothing.

## Why the verb is take

`ProposalAccepted` is the obvious name and it is deliberately unused.

It claims an act that did not happen. The event records that a step exists that ran what this proposal proposed, and nobody accepted anything: whoever composed the procedure may simply have gone ahead. Accepting says a party considered the proposal and said yes, which is the unbacked claim this tree refuses everywhere else.

It also spends a word that is needed. Approval by a person is a real future event on this stream, genuinely distinct from and prior to anything running, because an operator can approve something that then never runs. If Accepted means "a step cited it", the approval event has to be called Approved, and nobody will remember which is which.

Counsel is taken, which is the collocation the context's own name supplies, and it claims the least of the candidates: that somebody acted, and here is the acquisition that shows it. `ProposalFollowed` was the runner-up and claims slightly more, that what ran matched what was proposed, which only the plan half of is checked.

**Two constraints from the fitness suite shaped these names**, and they are recorded here because they are not obvious from reading the rules.

The command-to-event derivation takes only the FIRST token of a command as its verb and requires every remaining token to appear, in order, before it. So a phrasal verb cannot derive: `take_up_proposal` yields `UpProposalTaken` and nothing else, which is why the earlier `ProposalTakenUp` is not the name. Single-word verbs are effectively mandatory for any command in this repository.

`ProposalMade` needs one line added to the irregular-stem map, because the stemmer strips `-ed` and `-en` and `made` ends in neither. Adding `"made": "make"` beside `held`, `bound`, `taken` and `forgotten` is a true statement about English rather than an exception carved for this feature, which is the bar that map sets. Four verbs derive for free and were still rejected: submitted implies an adjudicator, raised collides with `raise` on every page of Python here, and offered and entered are both stilted. "Make a proposal" is the phrase people say, which is what R1 asks.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidProposalParametersError` | 400 | The values do not satisfy the plan's schema. |
| `UnauthorizedError` | 403 | The caller is known and not allowed. |
| `InvalidOccurredAtError` | 400 | A reported take time carried no timezone. |
| `PlanNotFoundError` | 404 | The id names no plan. |
| `ExecutionNotFoundError` | 404 | The id names no execution. |
| `ExecutionStepNotFoundError` | 404 | That execution holds no such step. |
| `ProposalNotFoundError` | 404 | The id names no proposal. |
| `ProposalAlreadyExistsError` | 409 | Aimed at an id that already has a history. |
| `ProposalCannotBeTakenError` | 409 | Already taken, or the step ran another plan or none. |
| `ConcurrencyError` | 409 | It changed between the read and the write. |
| `IdempotencyConflictError` | 422 | The same retry key arrived with a different body. |

Four of these are not this context's classes and it registers none of them. `PlanNotFoundError`, `ExecutionNotFoundError` and `ExecutionStepNotFoundError` are Execution's. `InvalidOccurredAtError`, which a take carrying a naive timestamp raises, belongs to the shared helper and is also mapped by Execution, as the context that first needed it. FastAPI's exception handlers are app scoped, so a second registration here is the duplicate [Patterns](../reference/patterns.md#rejections) warns about. Whether that reliance actually holds is not something the source can state, so the contract tier walks all four over a Counsel route.

`ProposalCannotBeTakenError` is per verb rather than a bare `ProposalCannotTransitionError`. R6's carve-out is for a verb with no foreseeable second, and there are two foreseeable, withdrawing and superseding.

Its three causes share a class and a status because the caller's next move is the same in kind: stop and work out which step it meant. That is the same shape `RunCannotBePausedError` already has, one verb with more than one way to be refused, and R6 is about not collapsing several verbs rather than several causes.

**Writing it added something the design had not.** Causes on one class need a discriminator, or a caller is told only that something is wrong. Which attribute is set is it: `taken_by` set means the proposal already has a step, and the error carries which; `step_plan_id` set means the step ran a different plan, and the error carries both plan ids; neither set means the step runs no plan at all.

**The third cause arrived with the step reference.** A run was always a run, so there were two ways to be refused. A step is a move or an acquisition, so a caller can now name something real that could never take a proposal, and that is worth a message of its own: told only that the plan did not match, a caller goes looking for a closer acquisition when what it needs is to stop looking.

## What an Inquiry is

An inquiry is a question put to a thinker about one execution, and what came back.

```
   Inquiry
     id                    a UUID minted when the question is written
     actor_id              the actor that asked
     execution_id          the execution the question is about
     objective             what the asker wanted to know
     execution_step_count  how many steps that execution had when they asked
     status                Open, Claimed or Answered, derived in the fold
     conclusion            one of four words, once something answers
     observed_step_count   how many steps the thinker had an outcome for
     execution_ended       whether the record was closed when it read
     proposal_id           the proposal the Propose arm wrote, and no other
```

A thinker reads an execution back, pairs what the procedure asked for with what became of it, and concludes one of four things: propose a run, stop, abstain, or refer it to a person. Only the first of those writes anything anywhere else. Before this aggregate existed the other three reached nothing at all, so the only thinking this system could see was the arm that happened to produce advice, and a thinker that looked carefully and concluded "nothing further is worth running" was indistinguishable from one that never ran.

## Why the Inquiry is here and not in Execution

An execution is one traversal of a procedure, and its stream is what became of that traversal. A question somebody asked about it afterwards is not something that became of it.

The [output-of-record test](../reference/modeling.md#choosing-where-an-act-is-recorded) settles it the same way it settles the Proposal. An inquiry's output of record is a conclusion, which no step produced and no engine reported. And an inquiry that concluded nothing worth running would sit in every count of how far its execution got, which is the failure that test exists to prevent.

It sits beside the Proposal rather than in a context of its own because the two share a language and one door. Both are advice, one put forward and one asked for; the Propose arm of an answer writes a proposal and names it, so a separate context would have opened a second cross-context door to reach its own neighbour, and this tree has already measured what those cost.

## The observation boundary

An inquiry may name an execution that is still walking. That is deliberate, and it is the case the aggregate is most useful for: somebody part way through a long procedure asking whether it is worth finishing.

It has a cost, and the record pays it rather than hiding it. A conclusion drawn from two reported steps of six is a weaker claim than the same conclusion drawn from six of six, and nothing downstream can tell them apart after the fact, because by the time anybody reads the inquiry the execution has moved on. So what the thinker could see is written down beside what it concluded.

```
   execution_step_count   captured when the question is put, from the execution
   observed_step_count    reported with the answer, by whatever read it
   execution_ended        reported with the answer, by whatever read it
```

**The denominator is captured and the numerator is reported, and the split is not arbitrary.** How many steps an execution has is fixed at its genesis and can never drift, so this system reads it off the execution itself rather than believing a caller who could make a partial reading look complete. How much of it a thinker actually saw is a fact about a reading that is over, and nothing here can check it. What the decider can check is that it is not impossible, and it does: seeing more steps than the execution has is refused.

**Two facts rather than one, because they answer two questions.** An execution can be closed with steps nobody reported on, and one with an outcome against every step has not necessarily been closed. A single number would collapse them, and both are ordinary.

None of the three is a quality score. They say how much was visible, never whether the conclusion was good. That is the same refusal that keeps a confidence off this record: a number a thinker assigns its own answer reads as measurement and is assertion.

## Three states, and why this one has a status

The Proposal derives its two states from a nullable reference and has no status field, because a two-valued enum beside a nullable field would be one fact written twice. The Inquiry has three, and no single field carries them.

```
   Open       the question exists and nothing is thinking about it
   Claimed    a thinker said it has this one
   Answered   a conclusion is on the record, and nothing further can land
```

Derived in the fold from which events the stream carries, never stored on a payload, for the reason an execution's status is: a status written onto an event could contradict the event it rode in on.

There is no running state between claimed and answered. An execution reaches one when a step is reported, and a thinking has no steps to report: it reads, concludes, and the record hears about it once.

The read model spells the same three states differently, out of two nullable timestamps and no status column, because there a column would be the second spelling this context refuses. That the two derivations agree is not visible in either one, so the port contract suite carries the case that separates them: an inquiry answered without ever being claimed.

## Where the claim sits, and what it is worth

Between the asking and the answer, refused from anything but open, and not a gate on answering.

A thinker handed its question never claims one, and answering from open moves the inquiry straight to answered. That is `claim_execution`'s posture and it is held for the same reason: a claim says who has the work, and refusing the answer would lose a conclusion this system was told in order to enforce an ordering the log does not have.

The claim is worth less here than it is on an execution, and the difference is worth stating. There, two drivers each believing they own one traversal both move a motor. Here, two thinkers reading one execution cost two inference calls and possibly two proposals for one question. Real, but not dangerous. So the claim exists for the case where something goes looking for work it was not handed, and `list_inquiries` with the status set to Open is what that something reads.

**Nothing expires a claim.** A thinker that dies holding one leaves a row that stays Claimed, and the listing narrowed to that status, with the time it was claimed on every row, is how an operator sees it. That is deliberately a view rather than a rule: a claim that timed itself out would release work this system cannot prove was abandoned. It is the same answer an orphaned execution gets, and for the same reason.

## Answered, and why the four conclusions are one event

An execution's four step outcomes are four event classes, because a field can be set wrong and a class cannot. The four conclusions are one event carrying a closed enum, and the divergence is deliberate.

Those four arrive from different reporting paths and carry different fields, so four classes make four wrong states unrepresentable. These four arrive from one call and three of them carry nothing at all, so the difference between them is one bit, whether advice came out of it, rather than four shapes. Four classes would also force four commands, and `abstain_inquiry` is not English.

What that trades away is a field that can be set wrong, and the decider is where it is caught: a Propose must name a proposal and the other three must not. The two refusals are opposite mistakes and share a class, so the class carries which one arrived, which is a lesson this context paid for once already.

The four words are spelled the same on both sides of the wire, because they are the thinker's own. There is no shared package holding them, which is the same arrangement the conductor has with this system.

## The five operations on an Inquiry

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Put a question | `POST /inquiries` | `make_inquiry` | `201` with the new id |
| Take one up | `POST /inquiries/{inquiry_id}/claim` | `claim_inquiry` | `204` |
| Record what was concluded | `POST /inquiries/{inquiry_id}/answer` | `answer_inquiry` | `204` |
| Read one back | `GET /inquiries/{inquiry_id}` | `get_inquiry` | `200` with the inquiry |
| Find them | `GET /inquiries` | `list_inquiries` | `200` with a page |

R8 runs between the first and the other two writes, the way it runs between this context's other pair. Asking is a speech act, so `make_inquiry` takes no `occurred_at` and this system is the authority for the moment. A thinker takes work up and concludes on its own clock somewhere else, so both of those accept one.

## The one free text in this context

A proposer's rationale was refused here: unbounded self-justification that will eventually quote a person, written into a table nobody can edit afterwards. An objective is allowed, and the distinction is which direction it points.

A rationale is the record defending itself. An objective is the input the answer is relative to, and a conclusion recorded without the question it answers cannot be read at all, let alone checked. It is bounded and trimmed, so it cannot grow into the reasoning this context still declines to hold, and the bound is also what lets it ride on a summary row: a list of questions with the questions taken out is a list of identifiers.

## What an Inquiry does not hold

**The case.** The thinker pairs a procedure with a record and hands the whole pairing to whatever does the thinking. None of it is copied here. `execution_id` reaches all of it, which makes this the one record in the tree that can point at its own basis rather than restating it, and it is the nearest thing to the basis this context has otherwise deferred.

**The reasoning, and any confidence.** What the thinker said, and how sure it was, are both assertions this system did not witness. Recording either would claim the cognition, which is the objection that kept the Proposal from being called a Decision.

**Which model, or which thinker beyond the principal.** An actor is whoever authenticated, and Access holds no marker saying whether that was a person or a piece of software. A field here would be a copy of a fact another context does not have.

## What it reaches across for

Execution, in one direction, for seven names. Nothing in Execution reaches back.

```
   plan.load_plan                       read the schema the parameters must satisfy
   plan.Plan                            the type a context module names
   plan.PlanNotFoundError               refuse a proposal naming no plan
   execution.load_execution             find the execution holding the step
   execution.ExecutionStep              the type the other context module names
   execution.ExecutionNotFoundError     refuse a take naming no execution
   execution.ExecutionStepNotFoundError refuse a take naming no such step
```

**Seven, where the design said two.** Writing it found the difference, and the difference is real rather than bookkeeping: a door is sized by what the consumer imports, and both decisions here read state off what they loaded, so both context modules name a type. Custody makes the same two existence checks and reads nothing off what it loaded, which is why its door is three names and does not include `ExecutionStep`. `test_tach_edges_are_used.py` is what keeps either claim honest, by failing on a name nothing takes up.

`Execution` itself is not on the list. The handler loads one, searches its steps and passes the step across, so the type is never written down.

This is the third cross-context door in the tree, and the doors are declared in `apps/keeper/tach.toml`.

`make_proposal` needs a context module holding the loaded plan, exactly as `define_procedure` does, because the decision reads a schema that lives on another stream and a decision function never reads from a store.

`load_execution` is doing more here than it does next door. In Custody the two checks establish that the step exists and the decision needs nothing from it, which is why that slice has no context module. Here the decision compares plan ids, so the step is state a decider reads and it travels across in a context module too. That is the same split [Patterns](../reference/patterns.md#cross-aggregate-validation) draws between a 404 and a refusal, landing on the other side of it than it did for a dataset.

The step, and not the execution around it. The execution is what makes the step findable; once it is found, nothing about the traversal bears on whether this acquisition ran the plan that was proposed.

`normalize_occurred_at` is not on that list, and its absence is this context's doing. `take_proposal` is its third consumer, which is what [Custody](custody.md#what-it-reaches-across-for) named as the trigger for moving it out of Execution and into `keeper.shared.instant`, where the table in [Layout](../reference/layout.md#where-shared-code-goes) says a pure helper with no `keeper` imports belongs. That move landed as its own commit before this context, so what would have been a third name on the door is an ordinary shared import instead.

## Where the code is

```
   apps/keeper/src/keeper/counsel/
     aggregates/proposal/       state, events, the fold, its two read paths, and
                                the summary a list shows with the port over it
     aggregates/inquiry/        the same five modules, for the question and
                                the answer
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the table in step with the log,
                                and the call that hands it to the worker
     features/
       make_proposal/           command, decision, handler, route, tool,
                                and a context module, for the plan it reads
       get_proposal/            a query slice, so no decider
       take_proposal/           and a context module, for the step it checks
       adopt_proposal/          composes, dispatches and records, in one append
                                across three streams and two contexts
       list_proposals/          the query a fold cannot serve
       make_inquiry/            and a context module, for the execution it counts
       claim_inquiry/           optional in the lifecycle, and refused from two states
       answer_inquiry/          the conclusion and the observation boundary
       get_inquiry/             a query slice, so no decider
       list_inquiries/          the query a fold cannot serve, filtered by status
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

Two read paths on the aggregate where Custody has one. A dataset gains no second event, so nothing ever appends to a stream that already has rows; a proposal does, and a handler about to append needs the version it folded from.

## What lands first

Two commits, and the split was where the database work starts. Both have landed.

**The first** was the aggregate, `make_proposal`, `get_proposal` and `take_proposal`. No projection, no migration, no new table, because events share one.

**The second** was `list_proposals`, with the projection table, its bookmark, a migration and the replay test. It was never optional, only later: until it existed nothing could ask what is still open, and that question is the loop. What made the split safe is that an agent holding the ids of its own proposals does not need the list to work.

The first commit moved `EXPECTED_BC_COUNT` to 5, `EXPECTED_AGGREGATE_COUNT` to 6 and `EXPECTED_SLICE_COUNT` to 25 in `test_fitness_scope.py`, and the count block on the [documentation home page](../index.md) is compared against those integers by `test_docs_match_code_constants.py`, so the page and the pins move together or the suite says so. It also added one entry to each of three other pinned sets: the stream types, the published OpenAPI paths, and the MCP tools a client should see. The second moved the slice pin again, added the migration's timestamp to `EXPECTED_SCHEMA_VERSION`, and added the list tool to the MCP walk, which pins tools by calling them rather than by listing them.

Two stemmers grew by one word between them, both in the test tier. `made` is the past participle of `make` and no suffix rule reaches it, so the command-to-event derivation and the event-name shape check each needed telling. Extending those maps is what their own docstrings ask for, and the alternative, loosening a suffix rule, is how a stemmer starts matching unrelated words.

**The third** was the Inquiry: the aggregate, its five slices, a second projection with its own table and bookmark, and a second port contract suite. It moved `EXPECTED_AGGREGATE_COUNT` to 9 and `EXPECTED_SLICE_COUNT` to 39, added one stream type, four OpenAPI paths and five MCP tools to their pinned sets, and moved `EXPECTED_SCHEMA_VERSION` to its migration's timestamp. No stemmer grew: `made` was already there from the Proposal, and `claimed` and `answered` are regular.

**The fourth** was adoption: `ProposalAdopted`, a `ProposalStatus` derived in the fold, an `adopted_at` column added to the summary rather than the table being rebuilt, and the `adopt_proposal` slice. It moved `EXPECTED_SLICE_COUNT` to 40, added an OpenAPI path and an MCP tool, and widened this context's door onto Execution from twelve names to eighteen, six of them reaching its feature layer for the first time.

## What is not here yet

**The basis.** What the agent looked at before it advised: datasets, prior runs, an objective. This is the part people mean when they say an agent has context, and it is deliberately absent from the first design rather than deferred within it. Three things have to be decided together and none is decided: whether ids in a basis are checked to exist, which is an existence check across a context door that does not scale from Custody's one to a set of forty; whether a basis is a field or a table; and what a reference means once the data behind it has changed, which is the question a record of what was pointed at, at a moment, cannot answer on its own.

**The campaign.** What a proposal is in service of, and where a goal and a stopping condition would live. It is an aggregate and probably a context, not a field here, and nothing asks yet.

**The agent.** An Actor in Access, as argued above, with the deciding software's version unrecorded. The trigger is something needing to ask a question about an agent across proposals.

**Approval.** A person saying yes before anything runs, which is where a beamline will want a human in the loop. `ProposalAccepted` is reserved for it. It is a third event and the one that turns `execution_id is None` into a real status enum.

**Withdrawing and superseding.** Two more plausible events, neither designed, each arriving as a class on the stream rather than as a field edited onto `ProposalMade`. Note that declined is unavailable as a word: `apps/reporter/src/reporter/outcomes.py` already uses it for this system refusing a transition.

**Any check that a taken proposal was followed.** The plan is compared and the parameters are not, so an acquisition that took a proposal and ignored half of what it said is recorded as having taken it. Closing that now needs two things rather than one: a decision about what counts as the same parameters, and somewhere to read the dispatched values from, which is the procedure rather than the execution.

**Any refusal of a proposal that leaves out what the plan requires.** The shared validator skips `required` when the values are empty, deferring it to the point where values are finally resolved and acted on, so a proposal naming a plan that demands an exposure time and proposing nothing is recorded. This was found by writing a test that assumed otherwise. It is not fixed here, because `define_procedure` has the same hole against the same validator and closing it for one surface and not the other would make two rules out of one. The decision belongs to the validator, not to this context.

**Any filter but openness.** Narrowing a list by proposer, by plan or by date is each a parameter and an index, and none has a caller: an agent holds the ids of its own proposals, and an operator asking what nobody acted on is asking exactly what `is_open` answers. The columns are already on the row, so each is small when somebody asks.

**Anything a projection could answer beyond finding a record.** How many proposals an actor makes, what fraction are taken, how long one waits before it is. The table has the columns for the last of those and no query asks it.
