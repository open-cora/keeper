# Pursuit

Pursuit is the bounded context that answers one question: what has a person authorized a machine to go and do on its own, and how far may it get.

It holds one aggregate. A pursuit is a bounded, goal-oriented, autonomous loop: it observes an execution, asks what should run next, dispatches the answer and observes that in turn, toward one goal within one beamline, one set of scopes and one budget, until the objective is met or a stopping condition is reached. Eight operations.

It is the newest context here, and the second whose subject is a permission rather than a thing. Authority holds the rulebook, which says which principals may call which commands and is general, standing and about the system. A pursuit is one person's authorization of one goal, bounded and revocable and about a stretch of time. The rulebook says an agent may adopt proposals at all; a pursuit is why one particular adoption at one particular beamline is allowed to happen with nobody watching.

## What a Pursuit is

One person's standing permission for a machine to chase one goal, with limits on how far it may get.

```
   Pursuit
     id          a UUID minted when the pursuit is started
     actor_id    who authorized it
     goal        what it is chasing, in words
     beamline    the one place its work may run
     scopes      the equipment it may drive
     budget      the limits, in one or more dimensions
     status      Running, Held or Stopped
     rounds      what it has asked and what came back, in order
     charged     what it has spent so far
     stopped_by  who took it back, if anybody did
```

Two of those fields are the reason the whole context exists. The beamline and the scopes say where a machine may work and what it may touch, and a person states both once here rather than every time something acts. Everything else is the record of what that permission went on to cause.

## The two facts that may not be inferred

The whole context follows from one gap, and the gap is in [Counsel](counsel.md#what-a-proposal-does-not-say-and-why-the-caller-must).

A proposal names an operation and the values to run it with. Turning one into work needs two more facts that a proposal does not carry: the beamline it runs at, and the scopes it may drive. Both are safety-bearing, and neither can be worked out from anything on the record. So adopting a proposal makes the caller state them, every time.

That is the right answer while the caller is a person. It becomes the wrong answer the moment the caller is software, because software stating a scope is software deciding what it may touch.

A pursuit is where a person states them once.

```
   without a pursuit          with a pursuit

   agent proposes             agent proposes
   person states beamline     person stated beamline once, when
   person states scopes       the pursuit was started
   person adopts              the round applies what they stated
```

Nothing in the closing handler could work the two out and nothing tries. They are read off the pursuit, and no caller has any way to supply its own. The permission is checked against a record written by a person, and every refusal is written down beside it.

## Why it is called Pursuit

The aggregate was deferred in Counsel under the name campaign, and the word did not survive contact with what it turned out to be. A campaign is something drawn up in advance, with a plan behind it, in a vocabulary borrowed from soldiering and from marketing. This carries no plan at all: it carries a goal and a limit, and everything between them is decided one round at a time by something that was not consulted when the goal was written.

Pursuit is the ordinary word for going after something without knowing in advance how. It also survives the failure cases, which is the test [Custody](custody.md#why-this-is-not-called-provenance) set: a pursuit that stalls is still a pursuit, and a pursuit somebody withdrew is one that was pursued for a while.

**Initiative** was rejected next door, as a name for Counsel, partly on the grounds that it also means a campaign and so collided with the sibling this became. That collision is now two real contexts rather than one and a deferral.

## The round, and why it is the unit

A pursuit does not turn in one call. Something has to happen at a beamline between the asking and the answering, and a thinker takes as long as it takes, so the asking and the answering are two calls and the round is what ties them together.

```
   open      observe one execution, put one question about it
             -> a round, numbered, and an inquiry to go with it

   ...       a thinker concludes, in its own time

   close     read the answer, act on it, end the round
             -> Advanced, Completed, Stalled or Referred
```

Rounds are numbered from zero in the order the pursuit opened them, the way an execution's steps are. The number is what the second call names, and it is what a round has instead of an id: a round is an element of one pursuit's list rather than a record anything else points at.

The execution a round observed does a second job. A pursuit refuses to open a second round about an execution it has already asked about, which makes opening one safe to retry and is most of the reason nothing has to claim a pursuit.

## Four outcomes, and why two of them hold

A thinker reaches one of four conclusions, and the inquiry already holds which. So closing a round is not four requests. It is one request to read an answer and apply it, and a caller that could name the outcome would be able to make a pursuit act on an answer nobody gave.

```
   the thinker said     the round        the pursuit is then
   --------------------------------------------------------
   Propose              Advanced         Running
   Stop                 Completed        Stopped
   Abstain              Stalled          Held
   Refer                Referred         Held
```

The two vocabularies are kept apart on purpose. A conclusion is what a thinker reached about an execution; an outcome is what became of a round. They coincide today and are not the same kind of fact, so the round cites the inquiry rather than copying what it holds, and `ANSWERS_TO` is the one place the translation is written down.

Only the advancing outcome leaves the pursuit running, and that asymmetry is the whole control flow: a loop continues while there is something to run and stops or waits otherwise.

**Holding is the decision this context was asked for twice.** Abstain and Refer could both have stopped a pursuit, and the argument for stopping is that a loop nobody is driving is a loop that should end. The argument that won is that both are answerable. Nothing to go on may stop being true when more data lands, and a referral is answered by whoever was referred to. Neither is a reason to throw an authorization away, so neither does, and `resume_pursuit` is how one comes back.

Completed is not reversible, and that is the only structural difference between the three that stop the loop turning. Resuming a completed pursuit would be restarting something somebody decided was finished, and doing it quietly is how an authorization outlives the intention behind it.

## A budget in five dimensions

A budget bounds consumption across one or more dimensions, whichever runs out first. It is a mapping rather than a row of nullable columns, because the dimensions a facility cares about are not the same everywhere, and a pursuit bounded only in tokens is as legitimate as one bounded only in hours. At least one is required: a loop with no limit at all is the thing this aggregate exists to make impossible.

The five split three ways, and the split decides what each costs to support rather than being a tidy grouping.

```
   counted     Rounds          off the pursuit's own events
               Executions      nothing reports these and nothing
                               can misreport them

   derived     WallSeconds     the clock against the moment it started,
                               so it needs no event at all

   reported    BeamSeconds     measured by whatever measures beam
               Tokens          counted by a thinker
```

Rounds and executions are two numbers rather than one because a round that concluded without a proposal spent inference and no beamtime.

The reported pair is the honest weak point. Neither is knowable here, so both arrive from outside and are only as good as whoever sent them: a thinker that crashed before charging what it spent got it free, and nothing here can tell. **A pursuit is a governor, not an accounting system.** A charge against one of the other three is refused, at the decider and again at the fold, because a number this record computes for itself would otherwise be counted twice, which is the direction that quietly gives a loop more room than it was authorized.

The budget is checked in exactly one place: opening a round refuses when any bounded dimension has run out. So what it limits is how many more times the loop may turn. Nothing stops a round already open from closing, and nothing refuses a charge that carries a dimension past its limit, because both of those describe consumption that already happened.

The check runs before the round is counted, so a pursuit bounded at eight rounds opens eight and refuses the ninth.

## Why there is no exhaustion event

Exhaustion is derived at the moment of asking and never recorded, and the reason is one dimension rather than a preference for derivation.

Wall seconds run out at a moment nobody is present for. An event saying so would have to be written by whoever next called in, which would date the exhaustion to the discovery rather than to when it happened, and a pursuit nobody called about again would never get one at all.

So there is no exhaustion event and no status for it. What a reader sees is a pursuit still authorized and a dimension with nothing left, which are two true facts rather than one invented one. The enum's declaration order decides which dimension is named when two run out together, so the answer is the same on every machine.

## Nothing claims a pursuit

Worth stating because the nearest neighbour does. Two conductors walking one procedure would move one motor twice, so a conductor claims the work it takes up.

Two callers driving one pursuit need no such thing. Both load the pursuit, both append at the version they folded from, and the store lets exactly one through; the loser is refused by the round it finds already there. The record is what serializes them.

That is what makes the thing driving a pursuit safe to duplicate, safe to restart, and cheap to move. A driver that crashed between opening a round and hearing about it comes back, tries the same execution, and is refused rather than opening a second round and spending the budget twice.

## Why the driver is not here

Nothing in this system reacts to an event by issuing a command, and a pursuit does not change that. Something outside notices that an execution ended and calls in, the way the conductor's work intake notices that one was dispatched.

That caller holds no authority at all. It cannot widen a scope, spend past a budget or reopen a stopped pursuit, because this aggregate refuses all three. It is a thing that notices and calls, and everything it may do is written on a record it cannot edit.

Where it should live is an open question and a reversible one, which is the consequence of needing no claim. One repository with two entrypoints is cheaper than a fifth mirror in this tree, and the conductor is the obvious host because it already holds a loop that watches for work and already speaks to this system over the same surface. Nothing here depends on that answer.

## The widest write in this tree

Closing a round on the advancing outcome writes four streams across three bounded contexts, in one append.

```
   procedure     composed, and dispatched as an execution
   execution
   proposal      adopted
   pursuit       the round closed, citing both
```

Two of those are Execution's, one is Counsel's and one is this context's. What is in the window a second append would open is a beamline running work against a budget that has not been debited, and a round that can be closed again because the first close never landed.

This does not call Counsel's adopting handler, because a handler appends on its own and the four writes would stop being one. It calls Counsel's decider for the fact Counsel owns, the proposal being adopted, and `keeper.execution.composing` for the run, and commits all of it with its own round beside them. The deciders are pure functions, so the decisions stay where they are modelled and only the append moves.

Opening a round is the same shape and smaller: two streams, the inquiry and the pursuit, decided by Counsel's decider and appended here.

**Both compositions live here because the dependency cannot point the other way.** Pursuit may read Counsel and does; Counsel knows nothing of Pursuit and must not, so a slice over there that loaded a pursuit would be a cycle rather than an edge.

## Who may start one, and what keeps that safe

Whoever authenticated, through either surface. All eight operations are published on MCP, including the one that hands out a standing permission, and that is worth stating rather than leaving to be noticed: every context here publishes every slice it has, so the default carried a heavier consequence this time than anywhere it had been applied before.

An agent can therefore start a pursuit. The alternative was an HTTP-only genesis, and it was rejected: a surface a person can reach and an agent cannot is a surface that gets worked around, and the check that matters is [Authority's](../reference/glossary.md) rather than which door the call came through.

What keeps it safe is not the door. It is that a budget cannot be raised, a scope cannot be widened, a stopped pursuit cannot be reopened, and every refusal is written down beside the pursuit that caused it. A pursuit is also the only way for software to get work dispatched without a person naming a beamline, so an agent that starts one has not gained a permission it could not otherwise obtain: it has gained a record of one.

`actor_id` is written by the handler from the authenticated principal, never supplied by the caller, the way a proposal's proposer and an inquiry's asker are. A standing authorization whose author is not on the record is not an authorization.

## Which commands may carry a time

R8 in [Naming](../reference/naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one) splits these five to one.

```
   start_pursuit         no time    authorizing is an act performed here
   open_pursuit_round    no time    so is putting a question
   close_pursuit_round   no time    so is reading an answer and acting on it
   resume_pursuit        no time    so is putting it back to work
   withdraw_pursuit      no time    so is revoking
   charge_pursuit        a time     it was consumed somewhere else
```

The five are speech acts, and a speech act happens where it is spoken: there is no earlier moment out in the world to be late to. Closing is the one worth arguing about, because an answer came from a thinker at some earlier moment. What the command does is tell this system to read an answer already on the record and act on it, and the moment this system acts is the moment the round ended. When the thinker concluded is on the inquiry.

`charge_pursuit` describes rather than makes, so it takes the caller's moment and falls back to the clock, beside `report_step` and away from the five around it.

## Idempotency, and the one transition that takes a key

Three of the six writing slices take a retry key and three do not.

```
   start_pursuit         key     a retry without one is a second standing
                                 authorization nobody asked for
   charge_pursuit        key     charges add rather than replace, so a
                                 redelivered one spends the budget twice
   withdraw_pursuit      key     the only transition in this tree with one
   open_pursuit_round    none    the pursuit refuses a second round about
                                 an execution it already asked about
   close_pursuit_round   none    a round that already closed refuses
   resume_pursuit        none    a running pursuit refuses
```

The three that go without are protected by something better than a cache: the domain refuses the duplicate. That matters most on closing, where the duplicate a retry would otherwise make is a second execution at a beamline.

**Withdrawing is the exception, and it is a deliberate one.** A 409 is the right answer to somebody stopping a pursuit that had already stopped, and the wrong answer to one person's own retry after a timeout. Those are different events and only a key tells them apart, so a replayed withdrawal carrying its key is a second 204 and a withdrawal arriving without one still meets the decider. The contract tier pins both halves, because a cache that answered every repeat would hide the fact worth being told.

Getting there meant fixing the chassis rather than this context. `with_idempotency` could not wrap a handler returning None: the store recorded a completed call by storing a non-null result, so a stored None read back as no row at all. Postgres refused the write after the handler had already appended its events, which is a 500 for a call that worked, and the in-memory adapter lost the row and ran the handler a second time.

The store names the state in a column now instead of inferring it from which column is null, which is the same move this context's read model made and for the same reason. `withdraw_pursuit` was the slice that found it, and is the first caller of the codec pair that had been sitting in the chassis unused and unusable.

## Why the read model stores a status

Every status in this system is derived in the fold and stored nowhere. On the read side that is not the question, because a projection has to write something into a row, and the question is whether the row carries a status at all.

Eight read models here, and five aggregates have a status at all: the operation, the procedure and the dataset have none, so their tables never faced the question. The five that did answer it two ways. The proposal and inquiry tables refuse a column, because their states only ever go forwards, so a nullable reference and a pair of nullable timestamps carry the whole of each and a status beside them would be one fact written twice. The execution, device and pursuit tables carry one.

The split is not stored against derived. It is whether the states go one way. A pursuit's do not: Held becomes Running when somebody resumes and may become Held again on the next round, so timestamps would have to record the last of an unbounded sequence rather than whether something happened. A device is the same shape, recovering much the way a pursuit resumes, which is why `proj_pursuit_pursuit_summary` is the third table here to carry a status and the second whose states revisit.

A written status can disagree with the fold, which is the cost all three pay. What makes the claim checkable here is that both sides answer one port contract suite and neither can see the other, and one of its twenty-two checks walks a single pursuit forwards and back through all three states.

Every arm of the projection writes values the event carries, because delivery is at-least-once and an arm that read the row before writing it would count a redelivered event twice. The round count is where that took a decision rather than falling out: a counter is the natural shape and it is the wrong one, so the count is written as the round's own index plus one, and a round delivered twice writes the same number twice.

A charge moves no column on this row. What a pursuit has spent is not on it, so subscribing would make the worker wake for every token a thinker reports.

## What it reaches across for

Four doors, which is more than any other context has, and the count is the price of being the context where the loop closes.

```
   keeper.execution.aggregates    4 names   two existence checks
   keeper.execution               1 name    compose_one_run
   keeper.counsel.aggregates      9 names   write an inquiry, read one back,
                                            adopt a proposal
   keeper.counsel                 5 names   two commands, one context, two
                                            deciders
```

Every door is sized by what this context actually imports, which is the only honest way to size one, and `test_tach_edges_are_used.py` is what keeps that true. `Execution`, `Operation`, `Proposal` and `Inquiry` are all loaded here and none of them is on a door, because the handler tests fields off them and hands them to deciders that declare their own types.

The Execution feature door is one name, and it would have been six. `compose_one_run` was extracted from Counsel's adoption slice before this context's second caller was written, precisely so that two contexts would not hold two copies of one account of how Execution composes a run. That the door is narrower is the smaller half of the gain. The larger half is that neither caller any longer knows that a procedure is defined and then dispatched, or that the dispatch needs the procedure folded first.

**Nothing reaches into Pursuit.** There is no door pointing this way and no sibling imports this package, which is what being the top of the stack looks like. The context reads three others and is read by none.

## The operations

| What it does | HTTP | MCP tool | On success |
| --- | --- | --- | --- |
| Authorize a loop | `POST /pursuits` | `start_pursuit` | `201` with the new id |
| Find them | `GET /pursuits` | `list_pursuits` | `200` with a page of pursuits |
| Read one back | `GET /pursuits/{pursuit_id}` | `get_pursuit` | `200` with the pursuit |
| Ask the next question | `POST /pursuits/{pursuit_id}/rounds` | `open_pursuit_round` | `201` with the question to answer |
| Act on the answer | `POST /pursuits/{pursuit_id}/rounds/{round_index}/close` | `close_pursuit_round` | `200` with what the round came to |
| Record what it spent | `POST /pursuits/{pursuit_id}/charges` | `charge_pursuit` | `201` with the running total |
| Let a held one carry on | `POST /pursuits/{pursuit_id}/resume` | `resume_pursuit` | `204` |
| Take the authorization back | `POST /pursuits/{pursuit_id}/withdraw` | `withdraw_pursuit` | `204` |

Rounds are a subcollection rather than a verb, because opening one creates something that is then addressable, and closing is a verb on the round rather than on the pursuit. Charges are a collection for the same reason: each call adds one to a list rather than transitioning anything. Both answer 201, beside the genesis, because all three create something. Resuming and withdrawing are verbs on the pursuit and answer 204, because neither creates anything and handing the record back would make the common case pay for the rare one.

The single read carries the whole authorization: the goal, the beamline, the scopes, the budget, who authorized it, whether it still stands and who stopped it. Every field is what somebody would be reading it to check.

The listing has two filters, which is [Equipment's](equipment.md#the-listing-and-why-it-has-two-filters) shape rather than Counsel's, and for a comparable reason: both filters have a caller who cannot work without one. The extra against the sibling listings is the beamline, and a pursuit names one in a way a proposal or an inquiry does not, because it is the authorization to run work there. So `?beamline=2-bm&status=Running` is the question somebody standing at a beamline asks, and `?status=Held` is the other one, which loops have stopped asking and are waiting for a person. Each row says which of the two answerable conclusions put it there, because one needs attention and the other needs data.

## What the stream holds

There is no pursuits table. A pursuit is worked out by replaying its events every time it is read.

```
   PursuitStarted      pursuit_id, actor_id, goal, beamline, scopes,
                       budget, occurred_at
   PursuitRoundOpened  pursuit_id, round_index, execution_id, inquiry_id,
                       occurred_at
   PursuitRoundClosed  pursuit_id, round_index, outcome, proposal_id,
                       dispatched_id, occurred_at
   PursuitCharged      pursuit_id, dimension, amount, occurred_at
   PursuitResumed      pursuit_id, actor_id, occurred_at
   PursuitWithdrawn    pursuit_id, actor_id, occurred_at
```

Opening and closing a round are two events rather than one, because something has to happen at a beamline in between and that takes as long as it takes. The opening names the run it looked at and the question it asked; the closing names what came back and the work that came of it.

A charge records what one round spent in one dimension, and charges add rather than replace. Only the two dimensions this system cannot measure for itself are written down; the other three are counted from the rounds, so writing one of those would count it twice and the attempt is refused.

The three events that stop or restart a pursuit each name the person who did it, because who took a permission back is the fact somebody will be looking for.

## What gets refused

| Refusal | Status | What happened |
| --- | --- | --- |
| `InvalidPursuitGoalError` | 400 | The goal is empty, too long, or not text. |
| `InvalidPursuitBeamlineError` | 400 | The beamline is not a usable name. |
| `InvalidPursuitScopesError` | 400 | The scopes are empty or malformed. |
| `InvalidPursuitBudgetError` | 400 | No limit was given, or one of them is not a positive number. |
| `InvalidPursuitChargeError` | 400 | The charge names a dimension this system counts for itself. |
| `UnauthorizedError` | 403 | We know who is asking and they may not. Different from 401, where we do not know. |
| `PursuitNotFoundError` | 404 | The id names no pursuit. |
| `PursuitAlreadyExistsError` | 409 | Starting was aimed at an id that already has a history. |
| `PursuitRoundCannotBeOpenedError` | 409 | The pursuit is not running, or it has already asked about this run. |
| `PursuitRoundCannotBeClosedError` | 409 | No such round, it is already closed, or its question has no answer yet. |
| `PursuitCannotBeResumedError` | 409 | It is running, or it was stopped for good. |
| `PursuitCannotBeWithdrawnError` | 409 | It has already stopped. |
| `ConcurrencyError` | 409 | The pursuit changed between the read and the write. Read it again and decide again. |
| `IdempotencyConflictError` | 422 | The same retry key came back with a different body, so no saved answer can be right. |

A budget with no limit at all is refused at the door. A loop with nothing bounding it is the exact thing this context exists to make impossible, so there is no way to write one down.

Refusing a second round about a run it has already asked about is what makes opening one safe to retry, and it is most of the reason nothing has to hold a lock on a pursuit.

## Where the code is

```
   apps/keeper/src/keeper/pursuit/
     aggregates/pursuit/        state, events, the fold, its two read paths, and
                                the summary a list shows with the port over it
     adapters/                  the two ways to read a summary: the projection
                                table, or a fold when there is no database
     projections/               what keeps the table in step with the log,
                                and the call that hands it to the worker
     features/
       start_pursuit/           command, decision, handler, route, tool
       open_pursuit_round/      two streams in one append, across two contexts
       close_pursuit_round/     four streams in one append, across three
       charge_pursuit/          the one describing command here
       resume_pursuit/          refused from two of the three states
       withdraw_pursuit/        refused from one
       get_pursuit/             a query slice, so no decider
       list_pursuits/           the query a fold cannot serve
     routes.py                  HTTP mounting and the error-to-status mapping
     tools.py                   MCP tool registration
     wire.py                    which handler gets idempotency, which gets tracing
```

No context module, although this context crosses more boundaries than any other. A context module exists to carry another aggregate's state into a pure decision, and none of the six deciders here takes one: what they decide is about the pursuit alone. Closing a round is the clearest case, because it looks like the exception. The outcome arrives already worked out, since working it out means reading an inquiry and a decision function never reads from a store, so the handler does the translation and the decider rules on whether the round may close at all.

Custody reaches across without one too, and for the opposite reason: there the sibling's state is checked for existence and nothing is read off it. The five that exist are in Counsel and Execution.

## What lands first

Four commits, and a fifth that is not this context's.

**The first** was the aggregate, `start_pursuit`, `withdraw_pursuit` and `get_pursuit`. No projection and no migration, because events share one table. It moved `EXPECTED_BC_COUNT` to 7, `EXPECTED_AGGREGATE_COUNT` to 10 and `EXPECTED_SLICE_COUNT` to 43, and added one stream type, three OpenAPI paths and three MCP tools to their pinned sets.

**The second** was one turn of the loop: `open_pursuit_round`, `charge_pursuit` and `resume_pursuit`. It is where the budget started being enforced and where the first cross-context append in this package landed.

**Then the seam**, which belongs to Execution rather than here. `compose_one_run` was extracted from Counsel's adoption slice, taking that context's door onto Execution's aggregates from eighteen names to twelve and its door onto the feature layer from six to one. It was done before the second caller was written rather than after, which is why this context's feature door was born at one name instead of being stood up at six and then cut down.

**The third** was `close_pursuit_round`, which is where the loop actually closes and advice becomes work without a person in the way. It is the widest write in the tree and the reason the seam was worth extracting.

**The fourth** was `list_pursuits`, with the projection, its table, its bookmark, both adapters, a migration and a port contract suite of twenty-two checks. It was never optional, only later: until it existed the only way to know a pursuit was running at your beamline was to have been told its id.

## What is not here yet

**Anything that reports what a pursuit has spent.** The aggregate computes all five dimensions and nothing publishes them. The single read returns the limits, the listing returns a round count, and a person wanting to know how much of a budget is left has to read the log. That is a gap rather than a decision: the arithmetic exists and no surface asks it.

**The driver.** Discussed above, and the only reason its absence is comfortable is that hosting it is reversible.

**Any second pursuit at one beamline being noticed.** A pursuit names a beamline and does not reserve it. Two at the same one are two records that happen to agree, and what stops them colliding is whatever stops two operators colliding. An event-sourced aggregate has no consistency boundary spanning its siblings, which is the same gap [Equipment](equipment.md#why-the-address-is-the-identity) refuses to hide for device addresses.

**Any way to give a pursuit more room.** A budget cannot be raised, and the honest way to authorize more is to start another pursuit. That is deliberate, and it costs something real: a loop that stalls one round short of its objective is restarted rather than extended, and the new record does not know what the old one learned.

**A reason on a withdrawal.** Why somebody stopped a loop is free text and this context holds none. It is the same refusal a proposal's rationale got, and it is weaker here, because a person withdrawing at two in the morning is exactly the person with something to say.

**Any account of what the loop learned.** A pursuit records what it was authorized to do and what it did. What made round six different from round five is in the thinker, which does not record it either.

**A schedule.** Nothing says when a pursuit should next act. That is the caller's business, and a field here would be an instruction this system has no way to carry out.

**Anything that makes exhaustion visible.** Two acts reach Stopped, a withdrawal and a round completing, and running out of budget is neither. It is a fact about the clock and a counter rather than something anybody did, which is why it has no event, and the consequence is that an exhausted pursuit reads as Running on every surface here. What it cannot do is open another round. A reader has to ask for the budget to tell the two apart, and the budget is the thing no surface reports.
