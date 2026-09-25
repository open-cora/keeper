# keeper

FastAPI + MCP backend for AROC. Python 3.13.

For repo-wide context see the [root README](../../README.md); for the rules
that govern code here, see [docs/reference/](../../docs/reference/index.md).

## Local dev

From the repo root, use the Makefile (`make install`, `make test`, `make dev`).
It delegates here automatically.

To run uv directly inside this app:

```bash
cd apps/api
uv sync
uv run pytest
uv run uvicorn keeper.api.main:app --reload
```

## Layout

```
src/keeper/
├── shared/           pure value objects and helpers; zero aroc.* imports
├── infrastructure/   ports, adapters, composition root, event-sourcing machinery
└── api/              FastAPI app, middleware, error handlers, MCP mount
```

Bounded contexts become siblings of these three, one package each. There are
none yet; that is the point of the baseline.

## Tests

Five tiers under `tests/`: `unit`, `architecture`, `integration`, `contract`,
`e2e`. The `integration` and `e2e` tiers need Postgres (`make db-up`); the rest
run with in-memory adapters under `APP_ENV=test`.
