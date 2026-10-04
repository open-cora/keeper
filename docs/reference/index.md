# Changing it

*The rules to keep when you edit this code, so it does not drift.*

For anybody writing keeper code, human or otherwise, and for whoever reviews it.
Not a tutorial. If the code disagrees with one of these pages, the code is wrong.

These rules came with the chassis, from an earlier private tree, stripped of that
tree's own vocabulary. The rules are the same. The examples started as
placeholders and most are now drawn from this tree's own contexts, so a page
reasoning about an operation or a run is reasoning about this one.
[Modeling](modeling.md) is the exception and still works in `Thing` and
`ThingRegistered` throughout.

## The pages

| Page | What it answers |
| --- | --- |
| [Naming](naming.md) | What to call an aggregate, an event, a command, a slice, a port, a URL |
| [Conventions](conventions.md) | Identifiers, units, personal data, schema-validated values, documentation |
| [Workflow](workflow.md) | Reading order, commits, branch flow, migrations, tests |
| [Layout](layout.md) | How a context is laid out, what shape a slice has, what may import what |
| [Modeling](modeling.md) | Events, value objects, grouping fields |
| [Patterns](patterns.md) | The read side, query slices, projections, repeated requests, refusals |
| [Runtime](runtime.md) | Production hardening, logging, HTTP errors |

The three client projects carry their own copies of [Naming](naming.md),
[Conventions](conventions.md) and [Workflow](workflow.md), holding the parts that
bind a plain Python library. They are shorter on purpose. Each ships as a
repository of its own and has to be able to keep its copy true, so a rule about
something a client does not have belongs here and nowhere else.

## A rule that ranges over nothing passes

A test that finds nothing to check reports green while examining an empty set,
and that looks exactly like green while examining everything.

So the suite in `tests/architecture/` guards its own reach.
`test_fitness_scope.py` pins the discovered context, aggregate and slice counts
to checked-in integers, and any rule that enumerates opens with a guard that
fails when its set is empty.

Those guards are not scaffolding left over from an empty tree. A renamed
directory, a pattern that stops matching, or a file moved to a new path all
shrink a rule's reach to zero without failing it, and each of those has happened
here.

## What the code looks like today

```
   bounded contexts    7     Access, Authority, Execution, Custody, Counsel,
                             Equipment, Pursuit
   aggregates         10     Actor, Policy, Operation, Procedure, Execution,
                             Dataset, Proposal, Inquiry, Device, Pursuit
   slices             53     four on Actor, four on Policy,
                             three on Operation, three on Procedure,
                             eight on Execution, seven on Dataset,
                             five on Proposal, five on Inquiry,
                             six on Device, eight on Pursuit
```

Those three match the integers `test_fitness_scope.py` pins, and
`test_docs_match_code_constants.py` compares this block against them, so
neither side can drift alone. That check was written after this block said it
was pinned and was not: the slice count sat at 15 while the code had 17. Test
counts are not quoted here, because a number in prose goes stale on the next
commit and nothing notices.

More tests check the shape of the codebase than check its behaviour, which is
out of proportion to the size of the domain and is deliberate: that every slice
carries the modules it needs, that no stored event can hold personal data, that
a stored name cannot be renamed without somebody noticing, that every context
is actually mounted in the running app, and that every test says which lane
runs it.

## What is missing

No tutorial and no how-to guides. The beamline page describes 2-BM and the one
script that reads it; nothing is running there, and its hardware register is
still empty. There is no page on the chassis itself, so how the event log, the
repeat-request wrapper and the startup wiring fit together is readable only
from the code.

Part of the chassis was copied from an earlier private tree and has no user
here yet. Which modules those are is pinned in
`test_unloaded_modules_are_pinned.py` rather than left to be rediscovered, so
the day a context starts using one, the suite says which one.
