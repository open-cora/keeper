# Keeping

*What the keeper writes down, what it guarantees about the record, and what it
refuses to decide.*

## The job

The keeper holds what happened and who is allowed to add to it. Everything else
in the system dials in to it: a person at a terminal, a conductor at a
beamline, a reporter beside an engine, a thinker wherever it runs. It calls out
to none of them.

```
   a person at a terminal     ----+
   a conductor at a beamline  ----+
                                  +---->   the keeper   ----  its database
   a reporter beside an engine ---+            |
   a thinker, wherever it runs ---+            |
                                               |
                                 nothing is ever dialled out
```

That direction is what lets one installation serve beamlines it cannot reach.
It also means the keeper learns nothing on its own. Every fact on the record
arrived because something told it.

Each fact is added once and stays. Nothing is edited and nothing is deleted,
because a record that can be revised afterwards is not evidence of anything.

## One fact, end to end

Everything written follows one path, whether it arrived from a person or from a
machine.

```
   a command arrives             as an HTTP route or as an agent tool,
                                 with the same code behind both

   who is calling                a principal, established at the edge
                                 and never taken from the command body

   may they issue this command   checked by command name against the
                                 one policy this deployment runs

   has this already been done    where the command creates something,
                                 a retry key makes a second delivery
                                 return the first result

   what does the record say      every event about that one thing,
                                 replayed to rebuild its state now

   does this follow              a decision with no I/O in it, which
                                 is what makes the rule testable

   append                        one or more events, insert-only at
                                 the database role rather than by
                                 convention

   the read models catch up      separately, on their own schedule
```

**No status is a fact anybody wrote down.** How far an execution got, whether a
device is faulted, whether a pursuit is still running: none of the three is a
field something set. Each is worked out from what happened, and asking about
one of them works it out from the history at that moment.

Asking for a list is the exception, and it is worth knowing which answer you
are holding. A listing reads a summary built as the events arrived, because
folding every stream to answer one page does not hold up at any size. That
summary is derived, rebuildable, and not the record: it can lag the log, and a
rebuild has once left a column behind that nothing writes any more. So a
listing is an answer about the record rather than the record, and the record is
the log.

### Seven contexts, one log

The model is divided into seven parts. Each answers one question in its own
vocabulary, and they share nothing above the log they all append to.

```
   Access   Authority   Execution   Custody   Counsel   Equipment   Pursuit
      |         |           |          |         |          |          |
      +---------+-----------+----+-----+---------+----------+----------+
                                 |
                      one append-only log
```

| Context | Answers |
| --- | --- |
| [Access](bounded-contexts/access.md) | Who the people and machines are |
| [Authority](bounded-contexts/authority.md) | Who may issue which command |
| [Execution](bounded-contexts/execution.md) | What can be run, what was put together, and what happened |
| [Custody](bounded-contexts/custody.md) | Where the data from a measurement is kept |
| [Counsel](bounded-contexts/counsel.md) | What was suggested, and whether anyone took it up |
| [Equipment](bounded-contexts/equipment.md) | What hardware exists, and what it was last reported doing |
| [Pursuit](bounded-contexts/pursuit.md) | What a person allowed a machine to do alone, and how far it may get |

Dividing it this way is what lets one part use a word strictly without
arguing about it elsewhere. A fault in Equipment is a judgement somebody
reported, and a claim in Counsel is a thinker saying it has the question. The
two words never have to mean one thing.

## What it promises

**Nothing can be quietly revised.** Appends are insert-only at the database
role, so this holds against the code that writes it rather than depending on
that code being careful. Retiring a device, withdrawing a pursuit and ending an
execution all add a fact; none removes one, and the history stays readable
afterwards.

**Every action has an authorization somebody can point at afterwards.** A
suggestion becomes real work only against permission granted in advance, and
the decision is written down beside the work it produced.

**A machine can be granted less than a person, and the difference holds.**
Every operation is published twice out of one piece of code, as an HTTP route
and as an agent-protocol tool. Which surface a call arrived through travels
with it into the authorization check, so a narrower grant to a machine is
enforced rather than described. [The surface](surface.md) lists all of them,
and is generated from the code so it cannot drift.

**The two facts a suggestion underdetermines are stated in advance.** Which
beamline work runs at and which equipment it may touch are fixed when the
permission is granted, by whoever granted it. Neither is ever read out of what
the suggestion said, because a machine that could name its own beamline and its
own devices would be writing its own authorization.

**A loop has a limit before it starts.** An autonomous pursuit carries a budget
in at least one dimension, because a loop with no limit is the thing that
context exists to make impossible. The limit is checked when the loop goes
round again, so it bounds how many more turns there may be rather than
anything already in flight.

## What it refuses to decide

**Whether a run was any good.** A report says what something was told, never
what was true. An instrument reporting success is a claim, and treating a claim
as a measurement is how a system produces confident wrong data, so the record
says reported and never witnessed. To witness is to have been present and able
to vouch, and the keeper was neither.

**That silence means anything.** A fact nobody reported reads exactly like one
that never happened. Nothing here can tell a quiet beamline from an unreported
one, and no absence on the record should be read as evidence that nothing
occurred.

**Which of two accounts of one step is right.** A step carries what the driver
observed and what the engine said about the run it opened, and the two are
allowed to disagree. Neither is reliable, so collapsing them would mean picking
a winner between two claims the keeper cannot check. It keeps both and leaves
the disagreement visible.

**Why something failed.** A failure reaches the record as the class of thing
that went wrong and never as a sentence about it. Free text in a record nothing
can edit afterwards is a liability, and whoever needs the why needs the logs of
whatever failed, not this.

**That work stops being claimed when nobody is driving it.** A conductor or a
thinker that dies holding a claim leaves a row claimed, and nothing expires it:

```
   expiring the claim         would assert the work was abandoned,
                              which cannot be proved from here

   leaving it claimed         is a true statement that somebody has
                              to go and look at
```

So finding abandoned work is a question a reader puts to the record, asking
what has been claimed longer than it plausibly takes, rather than a rule that
decides on their behalf.

**That a budget is an accounting system.** Two of the dimensions a pursuit can
be bounded in cannot be measured from here and have to be reported in, so a
budget is only as honest as whatever charges against it. It is a governor, and
a facility that needs real accounting needs something else as well.

## Where it stops

The keeper runs nothing. Four things sit on the other side of that line:

```
   driving hardware              a conductor, at the beamline
   running a routine             an engine, wherever the site put one
   keeping the data              a store
   deciding what to run next     a thinker
```

Each is named by what it does rather than by which product does it, because
which one a facility runs is that facility's fact and not part of this model.
The keeper holds a reference to the thing and never the thing itself.

[Running one](running.md) covers what a deployment has to supply and the order
the authorization bootstrap has to happen in. [The surface](surface.md) lists
every operation. [Contract](reference/client-contract.md) covers what a client
may rely on, and [Glossary](reference/glossary.md) pins every word here to one
meaning.
