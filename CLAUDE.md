# Repo guidance

This file is read by Claude Code (and other agents that respect `CLAUDE.md`). Keep it as a pointer file, not a long doc; the real conventions live in `docs/reference/`.

## What this repo is

The keeper is a parallel modeling effort on an inherited chassis: event-sourced bounded contexts over Postgres, hexagonal ports and adapters, paired REST and MCP surfaces, one handler per command.

The chassis was copied once, from an earlier private tree, and is owned outright from that point on. There is no shared package with that tree and no expectation that a fix in one lands in the other. Do not reach into it for code, and do not add provenance comments pointing at it.

The domains are the open question. The baseline carries zero bounded contexts on purpose, so the first ones can be modeled without inheriting a vocabulary.

## Conventions

- **Codebase layout, naming, BC structure, patterns**: [docs/reference/](docs/reference/index.md)
- **Identifiers, units, personal data, schema-validated values, documentation**: [docs/reference/conventions.md](docs/reference/conventions.md)
- **Docstring + comment + test-doc style specifically**: [docs/reference/conventions.md#documentation](docs/reference/conventions.md#documentation)
- **Which home a claim belongs in (docs page vs docstring), and the ban on claiming enforcement that does not exist**: [docs/reference/conventions.md#which-home-a-claim-belongs-in](docs/reference/conventions.md#which-home-a-claim-belongs-in)
- **Glossary**: [docs/reference/glossary.md](docs/reference/glossary.md)

## Hard rules carried into every change

- No phase, iteration or audit tags in source, tests or documentation: a plan
  coordinate, an iteration label, a dated audit tag, a numbered review
  finding. Git log is the right home, and
  `tests/architecture/test_no_phase_markers.py` spells every shape it
  refuses.
- No emoji anywhere in source: comments, docstrings, log strings, error messages, `Field(description=...)`.
- No em dashes in user-facing prose; use commas, colons, or rephrase.
- Default to no `#` comments. Add one only when the WHY is non-obvious.
- Test names carry scenarios (`test_<subject>_<scenario>_<expectation>`); per-test docstrings stay rare.
- A docstring may not name a symbol or a file that does not exist. Backticks mean "this is a symbol"; use a plain word when you mean a word. Enforced by `test_docstring_references_resolve.py`, which declares its two exception sets inline.

## Architecture fitness tests

`tests/architecture/` holds structural checks that range over whatever bounded contexts exist. With zero BCs they find nothing to check and pass vacuously, which is a false negative, not a green light.

`test_fitness_scope.py` pins the discovered-BC count to a checked-in integer for exactly that reason. Adding the first BC is meant to fail it. When that happens, confirm the fitness suite now ranges over something real, then bump the integer in the same commit.

## Memory hygiene

Auto-memory grows monotonically without a forcing function. These rules curb drift between sessions. They apply to this repo's Claude auto-memory directory: `~/.claude/projects/<repo-path-slug>/memory/`, where `<repo-path-slug>` is the repository's absolute path with `/` replaced by `-` (it differs per machine).

- A new memo's one-line pointer goes in `MEMORY.md` under the shelf that fits: a durable convention, principle, or pattern, a user fact, or feedback.
- Before creating a new memo, grep the index for the topic; prefer edit-in-place over a new file.
- Mutable status does not belong in index descriptions; the index carries the durable claim, the file carries the status.
- Any index description containing a count or a date older than 7 days requires a Read of the underlying file before quoting in chat.
- Memo files over ~300 lines: split into 2-3 sibling files linked from the first.

The keeper's memory is separate from that tree's because the project path differs. Chassis-level memos (naming rules, test infra, commit cadence, writing style) may be re-derived here; domain memos must not be carried across.

## Commits

One-line subject, body explains WHY. Recent commits set the tone; read `git log --oneline -10`.
