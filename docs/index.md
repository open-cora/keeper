---
template: home.html
---

# Keeper

The system of record for the experiment.

An event-sourced system of record, built on the chassis from its sibling project CORA, which is not public, and modelling its own domains.

## Where the documentation stands

Six bounded contexts exist. Access, Execution, Custody, Counsel and Equipment have pages below; Authority does not yet, and is readable only from its code. Two pages were written the other way round, before their code rather than after: Counsel's, which has since been corrected against what landed, and Conducting, which describes a direction the code has only started on and says throughout which parts are not there. The reference pages were carried over with the chassis and describe rules that are real. Most of them now argue from this tree's own contexts; `modeling.md` is the one still working entirely in placeholders, and the table below says which is which.

| Page | Subject | State |
| --- | --- | --- |
| [Access](bounded-contexts/access.md) | The Actor aggregate and its four operations | Current, written against the shipped code |
| [Execution](bounded-contexts/execution.md) | The Plan, Procedure and Execution aggregates, what this system can be asked to run, what it composed out of that, and what happened when it was carried out | Current, written against the shipped code |
| [Custody](bounded-contexts/custody.md) | The Dataset aggregate, and where the data one acquisition produced is being kept | Current, written against the shipped code |
| [Counsel](bounded-contexts/counsel.md) | The Proposal aggregate, what an actor put forward to run next, and whether an acquisition took it | Current, written against the shipped code |
| [Equipment](bounded-contexts/equipment.md) | The Device aggregate, what hardware this system knows about, and what it was last reported doing | Current, written against the shipped code |
| [Workflow](reference/workflow.md) | Reading order, commits, migrations, tests, mutation runs | Current |
| [Conventions](reference/conventions.md) | Identifiers, units, personal data, stored names, documentation | Current |
| [Layout](reference/layout.md) | BC structure, slice shapes, imports | Carried, examples now from this tree |
| [Modeling](reference/modeling.md) | Event sourcing, value objects, field grouping | Carried, examples are placeholders |
| [Patterns](reference/patterns.md) | Read side, queries, projections, idempotency | Carried, examples now from this tree |
| [Naming](reference/naming.md) | Aggregates, events, commands, slices, ports, URLs | Carried, examples now from this tree |
| [Runtime](reference/runtime.md) | Hardening, logging, HTTP errors | Current, written against the shipped wiring |
| [Glossary](reference/glossary.md) | Terms used the same way in code and prose | Carried |

## What is missing

A page on the Authority context, which holds the Policy aggregate and the four slices that author a policy, edit one and read one. No tutorial and no how-to guides. The beamline page describes 2-BM's descriptor and the one script that reads it; nothing is running there, and its device register is still empty. There is no page on the chassis itself, so how the event store, the idempotency wrapper and the kernel fit together is currently readable only from the code and its docstrings.

## What the code looks like today

```
   bounded contexts    6     Access, Authority, Execution, Custody, Counsel,
                             Equipment
   aggregates          8     Actor, Policy, Plan, Procedure, Execution,
                             Dataset, Proposal, Device
   slices             34     four on Actor, four on Policy,
                             three on Plan, three on Procedure,
                             seven on Execution, three on Dataset,
                             four on Proposal, six on Device
```

Those three match the integers `test_fitness_scope.py` pins, and `test_docs_match_code_constants.py` compares this block against them, so neither side can drift alone. That check was written after this page said it was pinned and was not: the slice count sat at 15 while the code had 17. Test counts are not quoted here, because a number in prose goes stale on the next commit and nothing notices.

The architecture tier holds more tests than any other, which is out of proportion to the size of the domain and is deliberate. Those tests check the shape of the codebase rather than its behaviour: that every slice carries the modules its shape requires, that no event payload can hold personal data, that a stored name cannot be renamed without noticing, that every bounded context in the tree is actually mounted in the running app, and that every test declares which lane runs it.

Part of the chassis was copied from the sibling project and has no user here yet. Which modules those are is pinned in `test_unloaded_modules_are_pinned.py` rather than left to be rediscovered, so the day a context starts using one, the suite says which one.
