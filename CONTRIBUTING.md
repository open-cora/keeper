# Contributing

The keeper is a personal research repository. It is public so the work can be read,
cited, and learned from, not because it is soliciting contributions.

## Where the code is developed

This repository is a published mirror. The work happens in
[open-cora/cora](https://github.com/open-cora/cora), a development tree holding
this project and the clients that call it side by side, and this repository is
extracted from `apps/keeper` with `git subtree`, so the history here is the
real history rather than a squashed import.

That matters for one practical reason: a change merged here would be
overwritten by the next publish. Open an issue, or fork, and say which of the
two trees you read. Everything below applies to a change made in either place.

## What is welcome

- **Questions and corrections.** If a document states something false, a
  convention contradicts the code, or a guarantee is claimed that nothing
  provides, please open an issue. That class of defect is the one this project
  most wants reported.
- **Discussion of the modeling.** The keeper exists to try domain designs on a
  settled chassis. If you have modeled something similar and reached a
  different answer, that is interesting and worth an issue.

## What is unlikely to be merged

- **Drive-by code pull requests.** The architecture is deliberate and most of
  it is documented in [docs/reference/](docs/reference/index.md). A change that
  reads as an improvement in isolation often violates a rule written down
  somewhere else, and reviewing that costs more than the change saves.
- **Dependency bumps and formatting changes.** These are handled in bulk.
- **New bounded contexts.** Those are the whole point of the project and are
  not delegated.

If you want to build on this, fork it. That is the intended use.

## If you do send a change

Read [docs/reference/workflow.md](docs/reference/workflow.md) first. In short:

```bash
make install      # uv sync
make precommit    # install the hooks, including the pre-push ruff pass
make lint typecheck arch-check
make test-noio    # no database needed
make db-up && make migrate-apply && make test-db
```

Three things that are easy to get wrong here:

1. **Stage your files before trusting an architecture run.** Ten of the
   fitness tests enumerate through `git ls-files`, so a file git has never
   seen is invisible to them. A green run on unstaged work means nothing.
2. **A new test must be able to fail.** Break the thing it names and watch it
   go red before you trust it. Several checks in this repository were found to
   be testing nothing exactly this way.
3. **Do not add a fitness test that ranges over nothing.** With no bounded
   contexts, most structural checks pass by examining zero subjects. See
   `tests/architecture/test_fitness_scope.py` and the "pending" rows in
   [docs/reference/naming.md](docs/reference/naming.md) for which rules are
   deliberately unenforced and why.

Commits follow Conventional Commits with a scope; the subject says what and
the body says why.

## Relationship to CORA

The keeper's chassis was copied once from its sibling project CORA, which is
not public, and is owned outright from that point. There is no shared package and no
expectation that a fix in one reaches the other. A patch here does not reach
CORA, and vice versa.

## License

Contributions are accepted under the [Apache-2.0](LICENSE) license of the
project.
