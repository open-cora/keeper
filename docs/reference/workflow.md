# Workflow

*Reading order, commits, branch flow, migrations, tests.*

The mechanics a contributor (human or LLM) has to internalise before touching the code. Each section is the rule, not the rationale; rationale lives next to the artifact it constrains.

## Reading order

Stop at any step and you have a working mental model of the layer above.

1. **The ports**: `apps/keeper/src/keeper/infrastructure/ports/`. The infrastructure seams (`Clock`, `IdGenerator`, `EventStore`, `IdempotencyStore`, `Authorize`, `TokenVerifier`).
2. **The composition root**: `infrastructure/kernel.py` and `infrastructure/deps.py`. What every BC is handed, and where it is built.
3. **The event-sourcing machinery**: `infrastructure/event_envelope.py`, `event_payload.py`, `evolver.py`, `idempotency.py`, `update_handler.py`.
4. **One fitness test**: `apps/keeper/tests/architecture/test_fitness_scope.py`. What is enforced mechanically, and why most of this directory is not enforcing anything yet.
5. **Vocabulary**: [Glossary](glossary.md).

Once the first bounded context exists, a vertical slice becomes step one and everything above shifts down.

## Commits

Conventional Commits with scope: `type(scope): subject`. Imperative, lowercase, no trailing period, under 72 characters.

| Type | Use for |
| --- | --- |
| `feat` | New caller-visible capability |
| `fix` | Bug fix |
| `refactor` | Internal restructure, no behavior change |
| `perf` | Performance |
| `test` | Tests only |
| `docs` | Docs only |
| `build` | Build, deps, packaging |
| `ci` | CI, pre-commit, hooks |
| `chore` | Anything else not user-visible |

**Scopes:** cross-cutting ones are `infra`, `api`, `db`, `obs`, `auth`, `arch`; repo-level ones are `repo` and `deps`. Each bounded context adds its own name as a scope when it lands. Pick the dominant scope or omit it.

**Granularity:** one commit is one cohesive change that compiles and passes tests. Port, adapter, and test for one capability is one commit. Refactor plus feature is two.

The subject line says WHAT; the body says WHY.

## Branch flow

Solo: commit directly to `main`. CI must be green before pushing.

**For anything non-trivial, use a worktree.** `git worktree add ../keeper-<task> main`, work there, commit, and return. Two reasons:

- A parallel session's checkout can destroy uncommitted work in the main tree.
- Pre-commit stashes unstaged changes to tracked files but [never untracked ones](https://github.com/pre-commit/pre-commit/issues/1212). A half-staged work-in-progress slice (untracked `handler.py` plus unstaged `wire.py` edits hidden by the stash) will false-fail architecture fitness functions and force `--no-verify` to land an otherwise-clean commit.

Also avoid `git commit -- <paths>` with mixed staged and unstaged state: the path form bypasses the index in a way pre-commit's stash flow does not expect. Stage everything and verify `git diff` is empty before committing.

## Migrations

Schema changes go in `infra/atlas/migrations/<timestamp>_<short_name>.sql`.

```bash
make migrate-new name=add_foo   # new empty migration
# edit the .sql file
make migrate-hash               # update the migration directory's atlas.sum
make migrate-apply              # apply locally
```

CI verifies `atlas.sum` and runs two grep-based scans on net-new files, both in `infra/atlas/scripts/`. `scan_destructive_ddl.sh` blocks `DROP TABLE`, `DROP COLUMN`, `TRUNCATE`, and `ALTER COLUMN ... TYPE` without a `USING` clause; its `-- atlas:safety:allow=<reason>` opt-out must be on the same line as the statement. `scan_constraint_drops.sh` blocks a dropped constraint or index with nothing added back in the same file; its opt-out is accepted on the offending line or on a standalone comment line above it.

**Forward-only.** A rollback is a new compensating migration, never an edit to a migration that has been applied anywhere.

## Tests

Descriptive-sentence pytest style: snake_case prefixed with `test_`.

```
test_<subject>_<expected_outcome>[_<scenario>]
```

- **subject**: the unit under test.
- **expected_outcome**: the property pinned, not the inputs.
- **scenario** (optional): conditions, introduced with `when_` or `for_`.

Optimize for the property, not the inputs.

**Good:**

```
test_decide_emits_thing_defined_when_stream_is_empty
test_handler_returns_thing_for_known_id
test_post_things_returns_201_with_thing_id
```

**Avoid:**

```
test_post_things_with_three_parts_in_order_b_a_c   # describes inputs
test_handler_3                                      # opaque
test_register_thing_works                           # outcome too vague
```

**Markers:**

- `@pytest.mark.unit`: pure, in-process.
- `@pytest.mark.architecture`: structural fitness functions (AST, filesystem, SQL text); no I/O.
- `@pytest.mark.integration`: real Postgres via `db_pool`.
- `@pytest.mark.contract`: REST and MCP schema verification via `TestClient(create_app())`.
- `@pytest.mark.e2e`: full end-to-end.

The marker is the category and the name is the property. Do not repeat the category in the name. Long names are fine.

Both the marker and its agreement with the folder are enforced. `test_every_test_file_declares_its_tier.py` requires a module-level `pytestmark` on every test file, naming the tier directory the file sits in. The folder and the marker are two statements of the same fact written by different hands, and while they disagree the file runs in one lane and not the other. The tier is the FIRST path segment under `tests/`, so a later `tests/unit/<bc>/` groups by bounded context without affecting it.

`test_every_tier_is_named_by_a_ci_lane.py` checks the other direction: every tier directory is run by a lane in both the Makefile and the CI workflow, and every path a lane names is a directory that exists. A directory under `tests/` counts as a tier unless its name starts with an underscore, which is how shared machinery such as `tests/_port_contracts/` declares that it is not one.

**File naming (integration tier).** Four suffix shapes cover everything under `tests/integration/`:

- `test_<slice>_handler_postgres.py`: single-slice, single-aggregate handler against real Postgres. `_postgres` is load-bearing: it disambiguates from the in-memory twin at `tests/unit/<bc>/test_<slice>_handler.py`.
- `test_postgres_<infra>.py`: the Postgres adapter itself is the subject.
- `tests/integration/scenarios/test_<subject>_<routine>.py`: a cross-BC walk stitching many slices to express one real routine. The `scenarios/` folder is the marker, so no `_scenario` suffix, and there is no in-memory twin, so no `_postgres` suffix either. One routine per scenario, no compendiums.
- `test_<subject>_postgres.py`: anything else against real Postgres. Use a descriptive infix when the test's specialness needs naming (`_cross_bc_`, `_atomic_`, `_full_fsm_cycle_`, `_race_`).

## Test coverage per slice

The slice pyramid below is convention, not yet enforcement: the fitness function that would check it needs slices to range over. Write it with the first bounded context.

| slice shape | decider | handler | endpoint | mcp_tool | handler_postgres |
| --- | --- | --- | --- | --- | --- |
| **command** | yes | yes | yes | yes | create-style only |
| **entry-append** | n/a | yes | yes | yes | create-style only |
| **query** | n/a | yes | yes | yes | n/a |

**Create-style** means a verb in `{define_*, register_*, add_*}`. These introduce a new aggregate or event stream, so the jsonb round-trip, `ON CONFLICT`, and unique-constraint behavior get pinned per slice against real Postgres. **State-transition** slices lean on cross-BC scenario coverage instead.

Detection is lenient: a slice counts as covered if either the 1:1 file `test_<slice>_<suffix>.py` exists, or another test file in the right tier mentions the slice name as a substring. The `EXEMPT_FROM_*` allowlists document existing divergences with citations.

## Idempotency contract tests

Create-style slices that accept `Idempotency-Key` get a dedicated `test_<slice>_idempotency.py` contract test. State-transition slices do not need them; the state machine rejects duplicate transitions naturally.

## Event-sourcing aggregate conventions

These are the checks to write as the first aggregate lands. **None exist yet**,
because each needs an aggregate to range over; listed here as the spec, not as
a description of what CI currently does:

- **`test_decider_purity`**: every `decider.py` is referentially transparent. No I/O, no clock, no UUID generation.
- **`test_decider_signature_canonical`**: every `decide` takes exactly `(state, command)` positionally; everything else is keyword-only after `*`.
- **`test_decider_docstring_invariants_block`**: every `decide` carries an `Invariants:` block enumerating its rejections inline with exception names.
- **`test_from_stored_wraps_payload`**: every `case "X":` in `from_stored` wraps `KeyError` / `TypeError` / `AttributeError` as `raise ValueError("Malformed X")`. Without the wrap, an error tracker groups every aggregate's `KeyError` into one undifferentiated issue. The payload value is intentionally not echoed, since payloads can carry correlatable identifiers.
- **`test_event_union_from_stored_coverage`**: every class in the `<X>Event` union is constructed by at least one `case` arm, and every `case` constructs a class in the union.
- **`test_event_payload_immutability`**: collection fields use `tuple[X, ...]` and `frozenset[X]`, not `list[X]` and `set[X]`.
- **`test_projection_idempotency`**: every projection's `apply()` is safe to re-run on the same event.

## A fitness test is only as good as what it ranges over

Most of the checks above iterate over discovered bounded contexts. With zero BCs they iterate over nothing and pass. A large green count is not evidence that a rule holds; it is evidence that the suite ran.

Two habits follow:

- **`test_fitness_scope.py` pins the discovered-BC count.** Adding the first BC fails it deliberately. Confirm the suite now ranges over something real, then bump the integer in the same commit.
- **Stage new files before the final architecture pass.** Fitness tests use git-aware discovery (`tracked_python_files()`), so a file git has never seen is invisible to them. A passing suite says nothing about an untracked file.

### Breaking a rule on purpose

A test nobody has watched fail is a file. Before a rule is trusted, break the thing it guards and confirm the rule, and ideally that rule alone, goes red.

Run one mutation with `apps/keeper/tests/_mutation/harness.py`:

```
cd apps/keeper
uv run python tests/_mutation/harness.py "the stream type is renamed" \
  -e "perl -pi -e 's/\"Actor\"/\"Aktor\"/' src/keeper/access/aggregates/actor/read.py" \
  tests/architecture
```

It prints one line per mutation: caught, with the tests that objected, or SURVIVED. Exit codes are 0 caught, 1 survived, 2 harness error.

It refuses to start unless the tree is fully staged, because only staged files can be restored, and it verifies after every run that the tree is byte-for-byte what it was. Both of those exist because their absence produced wrong answers here: `git checkout -- .` skips untracked files and is scoped to the current directory, so a batch silently accumulated one mutation's damage into the next one's verdict. It also refuses an edit that changed nothing, and refuses to read a non-zero exit as a catch without a `FAILED` line, since a bad path exits 4 and a target that collected nothing exits 5.

Run it once with no `-e` first. A baseline that reports SURVIVED is the proof the tool can report anything other than a catch.

## Per-BC test helpers

When a BC accumulates its own seeding and setup helpers, typically at the rule of three, they live in `tests/unit/<bc>/_helpers.py`, matching the shared `tests/unit/_helpers.py` and `tests/integration/_helpers.py` that will appear alongside them. Neither the shared helpers nor a fitness test rejecting divergent names exists yet.
