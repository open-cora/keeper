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

## Relationship to CORA

The keeper started from a copy of CORA's chassis and owns it outright from that point on.
There is no shared package, no vendoring registry, and no expectation that a fix in
one lands in the other. The two are free to diverge, including in the plumbing.

What was carried: the event store and its envelope, idempotency, the evolver and
update-handler scaffolding, ports and adapters for the cross-cutting concerns, edge
auth, observability, the test tiers, and the code conventions in
[docs/reference/](docs/reference/index.md).

What was left behind: every domain model. No bounded context here is CORA's, and the
contexts that exist were modelled from questions about a beamline rather than carried
across.

Nothing is claimed about individual words. An earlier version of this section promised
that CORA's facility vocabulary appeared nowhere in the tree, and that was already
untrue: `beam` is a message prefix in the reporter's fixtures, and both projects serve
facilities where a beam, an enclosure and a clearance are the plainest words available.
Two projects reaching the same ordinary noun for the same real thing is convergence,
and the line worth holding is against inheriting a model, not against sharing a
dictionary. What source may not do is explain this tree by describing that one, which
is CLAUDE.md's rule and is enforced by
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

Postgres binds host port **5433**, not 5432, and the Compose project is named
`keeper` explicitly. Both are so this can run alongside a CORA checkout: the two
repos' compose files sit in identically-named `infra/` directories, so without
an explicit project name Compose treats them as one project and starting either
one stops the other.

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

This repository is a published mirror. The work happens in
[open-cora/cora](https://github.com/open-cora/cora), a development tree holding
this project and its clients side by side, and each of them is extracted from
it with its history intact. Everything here is complete and runs standalone;
what it is missing is the other projects, and the end-to-end tests that need
more than one of them at once.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening anything, because where
a change lands depends on which of the two repositories you are looking at.

## Contributing

This is a research repository, public to be read rather than to solicit
patches. Corrections and questions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
