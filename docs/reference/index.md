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

So the suite in `apps/keeper/tests/architecture/` guards its own reach.
`test_fitness_scope.py` pins the discovered context, aggregate and slice counts
to checked-in integers, and any rule that enumerates opens with a guard that
fails when its set is empty.

Those guards are not scaffolding left over from an empty tree. A renamed
directory, a pattern that stops matching, or a file moved to a new path all
shrink a rule's reach to zero without failing it, and each of those has happened
here.
