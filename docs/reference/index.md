# Reference

For humans and LLM agents writing the keeper code, and for code reviewers. Not a tutorial. The rules to honor when modifying the keeper so the codebase does not drift. If the code disagrees with this page, the code is wrong.

These conventions were inherited from the sibling project CORA, which is not public, along with the chassis, then stripped of that project's domain vocabulary. The rules are the same. The examples started as placeholders and most are now drawn from the keeper's own contexts, so a page reasoning about a plan or a run is reasoning about this tree. [Modeling](modeling.md) is the exception and still works in `Thing` and `ThingRegistered` throughout.

## Pages

| Page | Subject |
| --- | --- |
| [Workflow](workflow.md) | Reading order, commits, branch flow, migrations, tests |
| [Layout](layout.md) | BC structure, slice shapes, imports, shared code |
| [Modeling](modeling.md) | Event sourcing, value objects, field grouping |
| [Patterns](patterns.md) | Read side, query slices, projections, idempotency, cross-aggregate validation, rejections |
| [Conventions](conventions.md) | Identifiers, units, personal data, schema-validated values, documentation |
| [Naming](naming.md) | Aggregates, events, commands, slices, ports, URLs |
| [Runtime](runtime.md) | Production hardening, logging, HTTP errors |
| [Client contract](client-contract.md) | How the peer clients in `apps/` name the same run |
| [Glossary](glossary.md) | Terms defined once and used the same way in code, commits, and prose |

## A note on rules that range over nothing

This page used to open by warning that the tree held no bounded contexts, so every rule here described a shape nothing had. That state is over. The mechanism it warned about is not, and it is the part worth keeping.

A fitness test that finds nothing to check passes. It reports green while examining an empty set, which is indistinguishable from green while examining everything. So the suite in `apps/keeper/tests/architecture/` guards its own reach: `test_fitness_scope.py` pins the discovered context, aggregate and slice counts to checked-in integers, and a rule that enumerates opens with a guard that fails when its parameter set is empty.

Those guards are not scaffolding left from the empty state. A directory renamed, a glob that stops matching, or a registrar moved to a new path all shrink a rule's reach to zero without failing it, and each of those has happened in this tree.
