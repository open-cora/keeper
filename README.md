# Keeper

*Themis, goddess of order and justice*

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)

The keeper is a parallel modeling effort built on a settled architecture: event-sourced
bounded contexts over Postgres, hexagonal ports and adapters, and equivalent REST
and agent-protocol (MCP) surfaces backed by a single handler per command.

The chassis is inherited and deliberately uninteresting. The experiment is the
domains modeled on top of it, and modelling them is what this repository is
doing now.

## Status

**Six bounded contexts, and two clients that talk to them.** Access holds
actors, Authority holds the rulebook that says who may issue which command,
Execution holds what can be asked for and what happened when it was carried
out, Custody holds where the data went, Counsel holds what was proposed, and
Equipment holds what hardware there is. Every operation is published twice, as
an HTTP route and as an MCP tool, from one handler.

Two clients call the API over HTTP and import nothing from it.
[conductor](https://github.com/open-cora/conductor) walks a dispatched
procedure across a beamline and reports each step;
[reporter](https://github.com/open-cora/reporter) relays one acquisition
engine's document stream and says where the data landed. Each is a repository
of its own, with its own lockfile and its own gate, and neither is a
dependency of this one.

The counted version of all that lives on the [documentation home
page](docs/index.md), where the numbers are pinned against the fitness suite and
cannot drift. They are not repeated here, because two copies of a count is one
copy and one liability.

## The inherited chassis

The keeper started from a copy of an earlier, private tree's chassis and owns it
outright from that point on. There is no shared package, no vendoring registry, and
no expectation that a fix in one lands in the other. The two are free to diverge,
including in the plumbing.

That tree is left unnamed here on purpose. It carried the name CORA first, which is
now the name of the development tree this project is published from, and one name for
two things costs a reader more than the provenance is worth.

What was carried: the event store and its envelope, idempotency, the evolver and
update-handler scaffolding, ports and adapters for the cross-cutting concerns, edge
auth, observability, the test tiers, and the code conventions in
[docs/reference/](docs/reference/index.md).

What was left behind: every domain model. No bounded context here came across, and
the ones that exist were modelled from questions about a beamline.

Nothing is claimed about individual words. An earlier version of this section promised
that the other tree's facility vocabulary appeared nowhere here, and that was already
untrue: `beam` is a message prefix in the reporter's fixtures, and both serve
facilities where a beam, an enclosure and a clearance are the plainest words available.
Two projects reaching the same ordinary noun for the same real thing is convergence,
and the line worth holding is against inheriting a model, not against sharing a
dictionary. What source may not do is explain this project by describing that one,
which is CLAUDE.md's rule and is enforced by
`tests/architecture/test_no_sibling_project_vocabulary.py`.

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
`keeper` explicitly for a related reason: Compose derives a project name from
the containing directory, so two checkouts whose compose files both sit in
`infra/` are treated as one project, and starting either one stops the other.

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

The clients are separate deployables on purpose. This project is the model and
its surfaces; a client is something that calls them over HTTP and runs where an
engine or a beamline is rather than where the database is. Neither imports the
other, and separate repositories are what make that the interpreter's rule
rather than a convention.

## Where the code is developed

**This repository is what you deploy, install and cite.** It is one
deployable, versioned and released on its own, and it runs standalone: its own
lockfile, its own suite, its own site.

**Development happens in [open-cora/cora](https://github.com/open-cora/cora)**,
a tree holding this project and its clients side by side, from which each is
extracted with its history intact. What is missing here is the other projects
and the end-to-end tests that need more than one of them at once.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening anything, because where
a change lands depends on which of the two repositories you are looking at.

## Contributing

This is a research repository, public to be read rather than to solicit
patches. Corrections and questions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
