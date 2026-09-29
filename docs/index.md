---
template: home.html
---

# Holds the record, and who may add to it.

The keeper writes down what happened and decides who is allowed to add to it. It holds what can be asked for, who may ask, what a person has allowed a machine to do on its own, what was run, and where the data went. Nothing is ever edited: each fact is added once and stays.

It is a record and a gate, and the gate matters more as the work stops being watched. Software can suggest anything. Whether a suggestion becomes real work is decided here, against permission a person granted in advance, and that decision is written down next to the work it produced.

**It runs nothing.** No hardware is driven from here, no measurement is started, and nothing outside is ever called. Everything talks to it and it talks to nothing, which is what lets it sit near the database while the work happens at the instruments.

## What it will not decide

**Whether a run was any good.** A report says what something was told, not what was true. An instrument reporting success is a claim, and treating a claim as a measurement is how a system produces confident wrong data. So the record says `reported` and never `witnessed`.

**What a machine may touch, based on what a machine said.** Two things can never be guessed: which beamline a suggestion runs at, and which equipment it may drive. Both are stated once, when the permission is granted, and everything after that uses what was stated rather than what the suggestion implied.

## What it holds

The model is split into seven bounded contexts. Each answers one question, and they share nothing but the event log underneath.

| Context | Answers |
| --- | --- |
| [Access](bounded-contexts/access.md) | Who the people and machines are |
| [Authority](bounded-contexts/authority.md) | Who may issue which command |
| [Execution](bounded-contexts/execution.md) | What can be run, what was put together to run, and what happened |
| [Custody](bounded-contexts/custody.md) | Where the data from a measurement is kept |
| [Counsel](bounded-contexts/counsel.md) | What was suggested to run next, and whether anyone took it up |
| [Equipment](bounded-contexts/equipment.md) | What hardware exists, and what it was last reported doing |
| [Pursuit](bounded-contexts/pursuit.md) | What a person allowed a machine to go and do alone, and how far it may get |

## The pages

**Running one**, if you have to stand this up and keep it running.

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | What it needs, the order the authorization bootstrap has to happen in, and what refuses to boot |

**Understanding it**, if you want to know what it holds and why.

| Page | What it answers |
| --- | --- |
| [The surface](surface.md) | Every route and MCP tool in one list. Generated, so it cannot be out of date |
| [Contract](reference/client-contract.md) | What a caller may rely on, and what it may not |
| [Glossary](reference/glossary.md) | Terms used the same way in code and prose |
| The seven contexts | One page each, listed above |

**Changing it**, if you are editing the code. These came with the chassis and describe rules that are real. Most now argue from this tree's own contexts; `modeling.md` is the one still working entirely in placeholders.

| Page | What it answers |
| --- | --- |
| [Overview](reference/index.md) | What these rules are for, and how they guard their own reach |
| [Naming](reference/naming.md) | What to call an aggregate, an event, a command, a port, a URL |
| [Conventions](reference/conventions.md) | Identifiers, units, personal data, stored names, documentation |
| [Workflow](reference/workflow.md) | Reading order, commits, migrations, tests, mutation runs |
| [Layout](reference/layout.md) | How a context is laid out, and what may import what |
| [Modeling](reference/modeling.md) | Events, value objects, grouping fields |
| [Patterns](reference/patterns.md) | The read side, queries, projections, repeated requests |
| [Runtime](reference/runtime.md) | Hardening, logging, HTTP errors |

## What the code looks like today

```
   bounded contexts    7     Access, Authority, Execution, Custody, Counsel,
                             Equipment, Pursuit
   aggregates         10     Actor, Policy, Operation, Procedure, Execution,
                             Dataset, Proposal, Inquiry, Device, Pursuit
   slices             48     four on Actor, four on Policy,
                             three on Operation, three on Procedure,
                             seven on Execution, three on Dataset,
                             five on Proposal, five on Inquiry,
                             six on Device, eight on Pursuit
```

Those three match the integers `test_fitness_scope.py` pins, and `test_docs_match_code_constants.py` compares this block against them, so neither side can drift alone. That check was written after this page said it was pinned and was not: the slice count sat at 15 while the code had 17. Test counts are not quoted here, because a number in prose goes stale on the next commit and nothing notices.

More tests check the shape of the codebase than check its behaviour, which is out of proportion to the size of the domain and is deliberate: that every slice carries the modules it needs, that no stored event can hold personal data, that a stored name cannot be renamed without somebody noticing, that every context is actually mounted in the running app, and that every test says which lane runs it.

## What is missing

No tutorial and no how-to guides. The beamline page describes 2-BM and the one script that reads it; nothing is running there, and its hardware register is still empty. There is no page on the chassis itself, so how the event log, the repeat-request wrapper and the startup wiring fit together is readable only from the code.

Part of the chassis was copied from an earlier private tree and has no user here yet. Which modules those are is pinned in `test_unloaded_modules_are_pinned.py` rather than left to be rediscovered, so the day a context starts using one, the suite says which one.
