# Keeper

*Everything is written down, and not everyone may write.*

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)

**The keeper writes down what happened and decides who is allowed to add to it.**
It holds what can be asked for, who may ask, what a person has allowed a machine
to do on its own, what was run, and where the data went. Nothing is ever edited:
each fact is added once and stays.

It is a record and a gate, and the gate matters more as the work stops being
watched. Software can suggest anything. Whether a suggestion becomes real work is
decided here, against permission a person granted in advance, and that decision
is written down next to the work it produced.

**It runs nothing.** No hardware is driven from here, no measurement is started,
and nothing outside is ever called. Everything talks to it and it talks to
nothing, which is what lets it sit near the database while the work happens at
the instruments.

Every operation is published twice, as an HTTP route and as an agent-protocol
(MCP) tool, out of one piece of code. A person and a machine reach the same model
through the same rules, which is what makes granting a machine less than a person
mean anything.

## What it will not decide

**Whether a run was any good.** A report says what something was told, not what
was true. An instrument reporting success is a claim, and treating a claim as a
measurement is how a system produces confident wrong data. So the record says
`reported` and never `witnessed`.

**What a machine may touch, based on what a machine said.** Two things can never
be guessed: which beamline a suggestion runs at, and which equipment it may
drive. A person states both once, when they grant the permission, and everything
after that uses what the person said rather than what the suggestion implied.

## What it holds

Seven bounded contexts, each answering one question and sharing nothing but the
event log underneath. **Access** holds the people and machines, **Authority** the
rulebook saying who may issue which command, **Execution** what can be run and
what happened when it was, **Custody** where the data went, **Counsel** what was
suggested to run next, **Equipment** what hardware exists, and **Pursuit** what a
person allowed a machine to go and do alone.

The counted version is on the [documentation home page](docs/index.md), where the
numbers are checked against the test suite and cannot drift. They are not
repeated here, because two copies of a count is one copy and one liability.

## The inherited chassis

The architecture under all of that is settled and deliberately uninteresting:
event-sourced bounded contexts over Postgres, hexagonal ports and adapters, and
equivalent REST and MCP surfaces backed by one handler per command. It started
from a copy of an earlier, private tree's chassis and has been owned outright
from that point on. There is no shared package, no vendoring registry, and no
expectation that a fix in one lands in the other.

That tree is left unnamed here on purpose. It carried the name CORA first, which
is now the name of the development tree this project is published from, and one
name for two things costs a reader more than the provenance is worth.

What was carried: the event store and its envelope, idempotency, the evolver and
update-handler scaffolding, ports and adapters for the cross-cutting concerns,
edge auth, observability, the test tiers, and the code conventions in
[docs/reference/](docs/reference/index.md). What was left behind: every domain
model. No bounded context here came across, and the ones that exist were modelled
from questions about a beamline.

Nothing is claimed about individual words. Two projects reaching the same
ordinary noun for the same real thing is convergence, and the line worth holding
is against inheriting a model, not against sharing a dictionary. What source may
not do is explain this project by describing that one, which is CLAUDE.md's rule
and is enforced by `tests/architecture/test_no_sibling_project_vocabulary.py`.

## Quick start

Requires Python 3.13.12 (via uv), Docker (for Postgres), and
[Atlas](https://atlasgo.io/) (for schema migrations).

```bash
make install        # uv sync this project
make precommit      # install git hooks (one-time per clone)
make db-up          # start Postgres on host port 5433
make migrate-apply  # apply the baseline schema
make test           # full suite
make dev            # API at http://localhost:8000, health at /health
```

Postgres binds host port **5433**, not 5432, so it does not collide with a
Postgres already running on the default port. The Compose project is named
`keeper` explicitly for a related reason: Compose derives a project name from the
containing directory, so two checkouts whose compose files both sit in `infra/`
are treated as one project, and starting either one stops the other.

## Layout

| Path | Contents |
| --- | --- |
| `src/keeper/shared/` | Pure value objects and helpers; no ports, no adapters |
| `src/keeper/infrastructure/` | Ports, adapters, composition root, event-sourcing machinery |
| `src/keeper/api/` | FastAPI app, middleware, error handlers, MCP mount |
| `src/keeper/<bc>/` | One package per bounded context, siblings of the two above |
| `tests/` | Five tiers: unit, architecture, integration, contract, e2e |
| `infra/atlas/` | Forward-only schema migrations |
| `docs/reference/` | Rules for writing code here |

## Related projects

Published from the same development tree, and separate deployables on purpose.
Nothing here imports any of them and none of them imports this; each calls this
one's HTTP API and runs where its own work is.

| Project | Does |
| --- | --- |
| [conductor](https://github.com/open-cora/conductor) | Runs the work at the beamline |
| [reporter](https://github.com/open-cora/reporter) | Reports what happened, and where the data went |
| [thinker](https://github.com/open-cora/thinker) | Suggests what to run next |

## Where the code is developed

**This repository is what you deploy, install and cite.** It is one deployable,
versioned and released on its own, and it runs standalone: its own lockfile, its
own suite, its own site.

**Development happens in [open-cora/cora](https://github.com/open-cora/cora)**, a
tree holding this project and the three above side by side, from which each is
extracted with its history intact. What is missing here is the other projects and
the end-to-end tests that need more than one of them at once.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening anything, because where a
change lands depends on which of the two repositories you are looking at.

## Contributing

This is a research repository, public to be read rather than to solicit patches.
Corrections and questions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
