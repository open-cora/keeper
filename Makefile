.PHONY: install dev db-up db-down db-reset lint typecheck test test-unit test-int \
        test-contract test-noio test-db test-coverage diff-coverage \
        docs-serve docs-build \
        fmt clean help migrate-status migrate-apply migrate-new migrate-hash \
        precommit precommit-run arch-check arch-show

# One project, one lockfile, one virtualenv. Every target runs here rather
# than looping over a tree, which is the difference between this Makefile and
# the one it was split out of. The root Makefile now calls these targets
# rather than repeating them, so a lane has one spelling wherever it runs.
STYLED := src tests

COMPOSE := docker compose -f infra/docker-compose.yml
ATLAS_DIR := infra/atlas
LOCAL_DB_URL ?= postgres://keeper:keeper@localhost:5433/keeper?sslmode=disable

help:
	@echo "Common targets:"
	@echo "  install         Install Python deps via uv, extras included"
	@echo "  dev             Run FastAPI dev server (reload, :8000)"
	@echo "  db-up           Start Postgres + pgvector via Docker Compose"
	@echo "  db-down         Stop Postgres"
	@echo "  db-reset        Stop Postgres and wipe its volume"
	@echo "  migrate-status  Show pending migrations against local DB"
	@echo "  migrate-apply   Apply pending migrations to local DB"
	@echo "  migrate-new     Generate a new migration skeleton (name=<short_name>)"
	@echo "  migrate-hash    Recompute atlas.sum after editing migrations by hand"
	@echo "  lint            Run ruff check + format check"
	@echo "  fmt             Run ruff format and auto-fix"
	@echo "  typecheck       Run pyright, strict"
	@echo "  test            Run the whole suite"
	@echo "  test-unit       Run only unit tests"
	@echo "  test-int        Run only integration tests"
	@echo "  test-contract   Run only contract tests"
	@echo "  test-noio       Run the no-DB CI lane (unit + architecture + contract)"
	@echo "  test-db         Run the DB CI lane (integration + e2e; needs db-up)"
	@echo "  test-coverage   Run all tests with coverage report (term + html + xml)"
	@echo "  diff-coverage   Run diff-cover against origin/main (fails if patch <90%)"
	@echo "  docs-serve      Serve the docs site at http://127.0.0.1:8024"
	@echo "  docs-build      Build the docs site, strict"
	@echo "  arch-check      Tach dependency contract + architecture fitness functions"
	@echo "  arch-show       Open the dependency graph (tach show)"
	@echo "  precommit       Install pre-commit hooks (one-time per clone)"
	@echo "  precommit-run   Run all pre-commit hooks against all files"
	@echo "  clean           Remove caches and build artefacts"

install:
	uv sync --all-extras

dev: db-up
	uv run uvicorn keeper.api.main:app --reload --host 0.0.0.0 --port 8000

db-up:
	$(COMPOSE) up -d postgres

db-down:
	$(COMPOSE) down

db-reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d postgres

lint:
	uv run ruff check $(STYLED)
	uv run ruff format --check $(STYLED)

fmt:
	uv run ruff check --fix $(STYLED)
	uv run ruff format $(STYLED)

typecheck:
	uv run pyright src tests

# pytest-xdist with `--dist=worksteal -n 4`: worksteal is the scheduler of
# choice for mixed-duration suites (50ms unit alongside 200ms+ integration).
# `-n 4` matches a 4-core CI runner, and the suite is I/O-bound on per-worker
# Postgres, so more workers oversubscribe Docker and asyncpg rather than
# helping. Each worker brings up its own container (see tests/conftest.py).
#
# Kept out of `[tool.pytest.ini_options].addopts` so ad-hoc single-file runs
# stay sequential and avoid worker-spawn overhead. Make targets opt in.
PYTEST_PARALLEL := -n 4 --dist=worksteal

test:
	uv run pytest $(PYTEST_PARALLEL)

test-unit:
	uv run pytest $(PYTEST_PARALLEL) -m unit

test-int:
	uv run pytest $(PYTEST_PARALLEL) -m integration

test-contract:
	uv run pytest $(PYTEST_PARALLEL) -m contract

# Local mirrors of the two CI test lanes (see .github/workflows/ci.yml).
# Path-based selection matches CI: it is the robust selector, since some
# helper and __init__ files carry no marker. test-noio starts no Postgres
# container (APP_ENV=test gives in-memory adapters); test-db needs `db-up`.
#
# The two files are compared against each other by
# tests/architecture/test_every_tier_is_named_by_a_ci_lane.py, which fails
# when a tier is named by one lane file and not the other.
test-noio:
	uv run pytest $(PYTEST_PARALLEL) tests/unit tests/architecture tests/contract --cov --cov-report=term-missing

test-db:
	uv run pytest $(PYTEST_PARALLEL) tests/integration tests/e2e

test-coverage:
	uv run pytest $(PYTEST_PARALLEL) --cov --cov-report=term-missing --cov-report=html --cov-report=xml

# diff-cover against the merge base, at a stricter bar than the suite-wide
# floor in pyproject.toml. Local only: no CI lane runs it, so it is a check an
# author chooses, not one a pull request has to clear.
diff-coverage:
	uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=90

arch-check:
	uv run tach check
	uv run pytest tests/architecture

arch-show:
	uv run tach show

# There is no committed OpenAPI snapshot and no target to write one. What
# guards the surface is EXPECTED_OPENAPI_PATHS in
# tests/contract/test_app_surfaces.py, which pins the published path set and
# fails when a slice lands or retires a route.
#
# Scope it honestly: that catches a route appearing or vanishing, not a
# response model changing shape. Catching the second needs a committed
# document and a test that diffs against it, and neither exists. A target that
# regenerated a file nothing reads used to stand here and claimed a drift test
# that was never written.

precommit:
	uv run pre-commit install
	uv run pre-commit install --hook-type pre-push

precommit-run:
	uv run pre-commit run --all-files

migrate-status:
	cd $(ATLAS_DIR) && DATABASE_URL=$(LOCAL_DB_URL) atlas migrate status --env local

migrate-apply:
	cd $(ATLAS_DIR) && DATABASE_URL=$(LOCAL_DB_URL) atlas migrate apply --env local

migrate-new:
	@if [ -z "$(name)" ]; then echo "Usage: make migrate-new name=add_foo"; exit 1; fi
	cd $(ATLAS_DIR) && DATABASE_URL=$(LOCAL_DB_URL) atlas migrate new $(name)

migrate-hash:
	cd $(ATLAS_DIR) && atlas migrate hash

# `atlas migrate lint` moved behind atlas-cloud login in v0.38; this project
# deliberately skips that path. CI runs a narrow grep-based safety scan on new
# migrations instead (see .github/workflows/ci.yml). Locally, read your
# migration carefully and `make migrate-apply` against a scratch database
# before merging: that catches the same class of issues lint would flag.

clean:
	rm -rf .pytest_cache .ruff_cache .pyright_cache build dist *.egg-info site
	find . -type d -name __pycache__ -exec rm -rf {} +

# The docs toolchain is not a project dependency: it is pulled per-invocation
# with `uv run --with`, pinned here so two machines render the same site.
MKDOCS := uv run --with mkdocs-material==9.7.7 mkdocs

docs-serve:
	$(MKDOCS) serve -a 127.0.0.1:8024

# `--strict` is what makes a broken cross-link fail rather than warn.
docs-build:
	$(MKDOCS) build --strict
