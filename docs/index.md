---
template: home.html
---

# Holds the record, and who may add to it.

The keeper writes down what happened and decides who is allowed to add to it. It holds what can be asked for, who may ask, what a person has allowed a machine to do on its own, what was run, and where the data went. Nothing is ever edited: each fact is added once and stays.

## Where this sits

Beamline software assumes somebody is watching. CORA is four programs for the case where nobody is, carrying the three things a person supplied by being present: the judgement about what to run next, the authority that made it permitted, and the account of what was actually done.

| | |
| --- | --- |
| **Keeper** | holds the record, and who may add to it |
| [Conductor](https://github.com/open-cora/conductor) | runs the work at the beamline |
| [Reporter](https://github.com/open-cora/reporter) | reports what happened, and where the data went |
| [Thinker](https://github.com/open-cora/thinker) | suggests what to run next |

**This is where the record and the permission live.** It runs nothing, and everything that runs reports here. [CORA](https://github.com/open-cora/cora) sets out why the four exist and how they fit.

## What it enables

**A machine can be granted less than a person, and the difference holds.** Every operation is published twice out of one piece of code, as an HTTP route and as an agent-protocol tool. A person and a machine reach the same model through the same rules, so a narrower grant to a machine is enforced rather than described.

**Every action has an authorization somebody can point at afterwards.** A suggestion becomes real work only against permission a person granted in advance, and that decision is written down beside the work it produced.

**Nothing can be quietly revised.** Each fact is added once and stays. A record that can be corrected after the fact is not evidence of anything.

## How

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

It sits beside its database and reaches nothing. No hardware is driven from here, no measurement is started, and nothing outside is ever called. Everything dials in and it never dials back, which is what lets one installation serve beamlines it cannot reach.

## What it will not decide

**Whether a run was any good.** A report says what something was told, not what was true. An instrument reporting success is a claim, and treating a claim as a measurement is how a system produces confident wrong data. So the record says `reported` and never `witnessed`.

**What a machine may touch, based on what a machine said.** Two things can never be guessed: which beamline a suggestion runs at, and which equipment it may drive. Both are stated once, when the permission is granted, and everything after that uses what was stated rather than what the suggestion implied.

## Where it stands today

Installed and running on a central host: the schema applied against a real Postgres, both services up under user-level systemd, and one beamline's devices registered and read back. What has not happened is a beamline turning the whole loop, because that needs the other three at once.

## The pages

| Page | What it answers |
| --- | --- |
| [Running one](running.md) | What it needs, the order the authorization bootstrap has to happen in, and what refuses to boot |
| [Keeping](keeping.md) | The path every written fact takes, what the record guarantees, and what it refuses to decide |
| [The surface](surface.md) | Every route and MCP tool in one list. Generated, so it cannot be out of date |
| [Contract](reference/client-contract.md) | What a caller may rely on, and what it may not |
| [Glossary](reference/glossary.md) | Terms used the same way in code and prose |
| [Changing it](reference/index.md) | The rules to keep when editing this code, and what the codebase looks like today |
