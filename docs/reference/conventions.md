# Conventions

*Identifiers, units of measurement, personal data, schema-validated values, documentation.*

Cross-cutting shapes that recur in every BC. Each family below has one chosen pattern and a short list of anti-patterns. Adopt the pattern when adding a field of that shape; deviate only with a reason.

## Identifiers

Every aggregate gets an opaque internal id at creation. External publication-quality identifiers (DOI, Handle, ORCID, ROR) are minted lazily, only when an outside system needs to cite the entity.

- **Internal id**: UUIDv7 produced by the `IdGenerator` port. Carried on every event payload and used as the stream id. Stable for the lifetime of the aggregate, never reused.
- **External id slot**: a nullable `external_id: str?`, or a typed `external_refs` map for entities that can carry several, populated by a later transition event when the external mint succeeds.
- **No coupling**: domain logic never depends on the external id being present.

The scheme is a docs and adapter concern, not a domain concern. The aggregate carries an opaque string and the namespace of the publishing system. Cross-entity links between externally published entities use the publishing system's own relationship vocabulary at the export adapter; the in-domain reference stays a plain UUID.

**Anti-patterns:**

- Do not use an external identifier as the primary key. Mint timing slips, schemes get renamed, and the cost of changing an aggregate's identity is high.
- Do not block aggregate creation on an external mint. A network failure on the mint side should never prevent an aggregate from being registered.
- Do not embed the scheme in the value (`"doi:10.1234/abc"`). Carry the namespace separately so the value stays opaque to it.

## Instance names

The human `name` on a registered instance is an intentional label for the thing's role, not a place to encode where it lives or who made it. The name is free-form: it is not a uniqueness key, and it does not derive the aggregate id. So it costs nothing to rename and nothing to choose well, which is exactly why it should carry meaning rather than a borrowed identifier.

- **Name the role, in this project's vocabulary**, not a vendor string or an external system's address.
- **One word; qualify only on a real collision.** Add a qualifier when a second instance actually exists, not before.
- **Deployment is not part of the name.** Scope fields and parent references already carry that.

A borrowed identifier has a home that survives the thing it was borrowed from being replaced: a vendor key on a bound catalog entry, an external address in an `alternate_identifiers` map, a serial or firmware version in `settings`. Keep the name out of their job.

**Anti-patterns:**

- Do not mirror an external system's address into the name because that is what operators type. Those identifiers have homes that survive a substitution; the name should survive it too.
- Do not pre-qualify against a hypothetical second instance. The qualifier is cheap to add when the collision is real.
- Do not encode the deployment in the name to make it globally unique. Names are not unique keys.

## Units of measurement

Numeric fields whose meaning depends on a unit carry the unit as a three-field annotation on the declaring JSON Schema, not in the field name. The annotation is `{system, code, label?}`.

```json
{
  "type": "object",
  "properties": {
    "duration": {
      "type": "number", "minimum": 0,
      "unit": {"system": "udunits", "code": "ms", "label": "milliseconds"}
    },
    "offset": {
      "type": "number",
      "unit": {"system": "udunits", "code": "mm"}
    }
  }
}
```

- **`system`**: namespace identifier (`udunits`, `ucum`, `qudt`, `iec61360`, `ucefact`). Closed allowlist enforced by `ALLOWED_UNIT_SYSTEMS` in `keeper.shared.json_schema.validation`, and this list is pinned against that constant by `test_docs_unit_systems_match_the_allowlist`.
- **`code`**: the unit token interpreted within `system`. Opaque to anyone outside that namespace.
- **`label`**: optional human display string for codes that are not self-explanatory.

The schema-declared unit is the canonical wire-and-storage unit. Deciders, events, projections, and API responses always carry the value in that exact unit. Conversion happens only at the edge.

**Anti-patterns:**

- Do not put units in field names. `offset`, not `offset_mm`. The whole point of the annotation is to escape the lock-in that field suffixes create.
- Do not add a `display_unit` second slot on the schema. Display is a per-user concern at the UI edge.
- Do not convert units inside deciders, evolvers, or projections. The domain ring carries one unit per field.
- Do not change the `system` or `code` of an existing field by editing the schema in place. Emit a new schema version and let downstream rebuild against it.

## Personal data

Nothing in this system holds personal data, and no machinery exists for holding
it. The rule below is the one to apply on the day something does, written down
now because the decision that keeps it cheap is being made continuously: every
field not added to an event payload is a field nobody has to erase later.

**The rule.** Personal data does not go in events. Events are immutable and
INSERT-only at the database role level, so a value written into a payload cannot
be taken back out. Personal data belongs in a separate mutable table keyed by the
subject's id, with the event payload carrying that id alone.

**Enforced.** `apps/keeper/tests/architecture/test_events_carry_no_personal_data.py` reads every event dataclass and every payload builder in every bounded context and refuses a field whose name appears in its deny-list, camelCase spellings included. It ranges over aggregates, so a new one is covered the moment it exists.

The check knows names, not contents. It stops a field called `email`; it cannot stop an `email` written into a field called `note`. That gap is what the last anti-pattern below is about.

**Anti-patterns:**

- Do not put personal data in event payloads. Events are immutable; personal data must be deletable.
- Do not encrypt-and-throw-away-the-key. Regulators increasingly treat encrypted personal data as still personal, and the operational complexity is high for no real benefit when a simple delete is available.
- Do not build the side table before there is personal data to put in it. It was built once here and removed unused; an empty vault is machinery guarding an empty room, and its shape is better argued with a real field in hand.
- Do not assume free-text fields are safe. A reason string on a transition event can carry a name or a contact detail by accident, and no check can see it: the rule above reads field NAMES, never values. With no side table to route the text into, the answer is to leave it off the event until there is one. `ActorDeactivated` carries no reason for exactly this reason.

## Schema-validated values

One aggregate declares a JSON Schema; another aggregate carries a dict of values validated against it at write time. The shared infrastructure lives in `keeper.shared.json_schema.validation` and exposes two functions:

- `validate_schema_declaration(schema, *, error_class)` runs on the declarer's write path. It rejects schemas that are missing, that have the wrong `$schema`, that use a keyword outside the allowlist below, or that fail to compile.
- `validate_values_against_schema(values, schema, *, error_class, no_schema_message)` runs on the carrier's write path.

Each BC keeps its own typed error class and passes it into the shared validator. Each maps to HTTP 400 via the BC's own route. Different classes mean log aggregators can identify the source BC without parsing message text.

**The keyword set is an allowlist, not a denylist.** Anything not named below is refused, which is a stronger claim than any list of banned keywords, and it is why this list is pinned against the code rather than left as prose.

- **Allowed anywhere in a schema**: (`$schema`, `enum`, `maximum`, `minimum`, `pattern`, `properties`, `required`, `type`, `unit`). Closed allowlist enforced by `ALLOWED_SCHEMA_KEYS` in `keeper.shared.json_schema.subset`, and this list is pinned against that constant by `test_docs_schema_keywords_match_the_allowlist`.

Two absences follow from it, and both are easy to trip over.

`additionalProperties` and `unevaluatedProperties` are absent, so **every stored schema is open at every object level**. A declared property that is `required` and missing is still refused; an undeclared property is accepted and stored alongside the rest. Typos in required names are caught, extra values are not. Closing this would mean allowing `additionalProperties` for the literal `false` only, because the keyword also takes a schema and that form would need `check_subset` to recurse into it.

`items` is absent too, so an array property can be declared an array and nothing more. A list of detector names and a list of arbitrary objects are the same declaration here. That is a weaker contract rather than a blocked one.

**Strict-by-default posture:** the carrier's validator follows a four-cell table that all instances share.

| schema | values | result |
| --- | --- | --- |
| absent | empty | accept (trivially valid) |
| absent | non-empty | reject with operator guidance |
| present | empty | accept (no required-field check at this layer) |
| present | non-empty | compile and validate; reject on first violation |

An operator wanting "this declarer genuinely has no values to constrain" declares an empty `{}` schema explicitly. The implicit "no schema, anything goes" path is closed by design.

**Anti-patterns:**

- Do not inline schema validation in slices. Always go through the shared validator with a BC-specific error class.
- Do not let carriers fall back to accept-anything when the declarer's schema is absent. The strict-by-default posture catches the common operator mistake of writing values before declaring how they should be shaped.
- Do not widen the allowlist without adding the corresponding evolver and projection support, and without teaching `check_subset` to recurse into any new keyword that takes a schema. The constrained subset is what lets the declarer's schema be stored, evolved, and rebuilt deterministically; a recursive keyword added without the recursion is a hole through which every forbidden keyword travels nested.

**Forward-compatible authoring discipline.** A declared schema is the strongest candidate to travel between deployments. The rules are borrowed from Linux Device Tree bindings.

- **Do not try to close the schema.** Device Tree's rule is to set `additionalProperties: false` and `unevaluatedProperties: false` at every object level, and unknown fields are indeed a contract break rather than a quiet extension point. Neither keyword is in the keeper's allowlist, so following that advice produces a 400. The rule is kept here because it is the right instinct and because what it costs to lack it is written down above, not because it can be obeyed today.
- **Vendor-prefix vendor-specific extensions only.** Properties shared across all instances of a family stay generic; properties specific to one supplier go under a dotted namespace. The generic form is reserved for cross-supplier consensus.
- **Describe the thing, not the driver.** Property descriptions name the quantity, range, and unit. They do not reference Python classes or any transport's address syntax. The same schema must serve two different substrates without edits.

## Time

Two timestamps ride every event, and they answer different questions.

| | `occurred_at` | `recorded_at` |
| --- | --- | --- |
| What it means | when the thing happened | when this system wrote it down |
| Who sets it | the handler, or the caller | the database, via `DEFAULT now()` |
| Can a caller influence it | sometimes, see below | never |

`recorded_at` is written by the `events` table's own default and is never sent from application code. That is what makes the other one safe to take on trust: however wrong a claimed time is, the row still says truthfully when it arrived.

**Which commands may carry a time is decided by R8 in [Naming](naming.md#r8-ask-whether-the-record-makes-the-fact-or-describes-one).** A command whose record MAKES the fact must not accept one: `register_actor`, `define_policy` and `define_plan` are acts this system performs, so the moment it writes one is the moment it happened, and a supplied time would be fiction. A command whose record DESCRIBES a fact something else produced may accept one, because the caller was there and this system was not.

Execution's six run commands are the first to take it. `define_plan`, in the same context, does not.

**A supplied timestamp must carry an offset, and is converted to UTC.** Both halves earn their place:

- A naive datetime is not an instant. `datetime.fromisoformat` returns one without complaint, and writing it into a `timestamptz` column makes Postgres apply the session timezone, so the row ends up stating a time nobody sent.
- Two spellings of one instant must be one value. The idempotency wrapper hashes a whole command, so a timestamp field joins that hash; a retry sending `Z` where the first attempt sent `+00:00` would otherwise be a different hash and come back as a conflict rather than the answer it already had.

**A supplied timestamp is not compared against the clock.** There is no future check and no ordering check, which is deliberate rather than pending. The clock cannot be read from a decision function, so any such refusal would have to live in a handler, which is where domain rules do not go. `Clock.now()` can jump backward under an NTP correction, which the chassis says in `MonotonicClock`'s docstring, so it is a poor referee. And `recorded_at` already makes an absurd claim visible next to the truth.

So a run may carry an `occurred_at` in the future, or before the run it belongs to. A reader ordering by it should order by `version` or `recorded_at` instead when they need the sequence this system actually observed.

## Stored names

Some strings are written into the database and later used to find those rows again. A stream type is the clearest case: it goes into the `stream_type` column on append, and into the lookup on load. Renaming one does not rename the rows already written, it hides them. These strings are wire formats, and changing one is a data migration rather than a refactor.

Every aggregate declares exactly one `<AGGREGATE>_STREAM_TYPE` constant, and its literal value is pinned by hand in `tests/architecture/test_stream_types_are_pinned.py`.

The pin exists because nothing else in the tree can disagree with the constant. The writing handler and the reading loader both import it, so they agree however it is spelled, and a round trip through a real database agrees too: every row read back was filed under whatever the constant said at write time. A rename moves both ends at once. A value spelled out once, by hand, somewhere that does not import it, is the only thing that can say no.

```
GOOD: ACTOR_STREAM_TYPE = "Actor"         pinned as "access/actor": "Actor"
BAD:  ACTOR_STREAM_TYPE = _derive_name()  the stored value is no longer readable from the source
```

This is the same habit as `EXPECTED_ACCESS_TOOLS` and `EXPECTED_OPENAPI_PATHS`, which spell out the surfaces published outward. A stream type is the surface published downward.

**Anti-patterns:**

- Do not import the constant into the pin. A pin that reads the value it is pinning agrees by construction, which is the defect it exists to close.
- Do not edit a pinned value to make a red run green. That run is the only notice that rows already on disk are about to stop being found.
- Do not compute a stream type. A value assembled at runtime is out of reach of every check that could protect it.

## REST URL paths

URL path segments use kebab-case. Hyphens, not underscores, separate words inside a literal segment.

```
GOOD: POST /things/{thing_id}/add-part
BAD:  POST /things/{thing_id}/add_part
```

Path parameter placeholders keep snake_case because FastAPI binds them to Python function arguments, which follow PEP 8.

Python handler function names, slice directory names, and command class names are unaffected. They stay PEP 8. The convention governs only the literal URL strings that external API consumers and OpenAPI specifications see. This wants a fitness test across every slice's `route.py`. There are no routes yet, so it is convention only.

### URL paths and slice/command/MCP names are independent conventions

Slice directory names, command class names, and MCP tool names carry the SUBJECT in the verb-phrase when the slice mutates a specific aggregate kind: `add_thing_part`, `retire_thing`, `update_thing_settings`. Read aloud, these are parallel English noun-phrases.

When the slice acts on a per-aggregate SUB-CONCEPT rather than the aggregate itself, the sub-concept noun is the subject. The command class still carries the aggregate qualifier while the slice directory and MCP tool drop it.

```
GOOD: slice = grant_permission/, command = GrantPolicyPermission,
      MCP tool = grant_permission,
      URL = POST /policies/{policy_id}/permissions

GOOD: slice = revoke_permission/, command = RevokePolicyPermission,
      MCP tool = revoke_permission,
      URL = DELETE /policies/{policy_id}/permissions/{principal_id}/{command_name}
```

The two URLs differ because a collection and a member of it are different resources. Posting to the collection adds to it and needs no member address; removing a member does, and a permission has no id of its own, so the pair that identifies it goes in the path.

A sub-concept noun has no aggregate folder to be derived from, so it is declared in `_DOMAIN_NOUN_ALLOWLIST` in `test_slice_verb_names_subject.py`, and here. The vocabulary today is two words:

| Noun | Aggregate it belongs to | What it is |
| --- | --- | --- |
| `permission` | `Policy` | one principal may issue one command |
| `step` | `Execution` | one element of the list an execution fixes at its genesis |

`test_module_names_match_their_type.py` accepts the resulting asymmetry: the folder's words must appear in the class name in order, with the aggregate qualifier inserted between them. Order is required, so `PermissionGrantPolicy` would not pass for a folder called `grant_permission`.

The asymmetry is not arbitrary. A slice directory and an MCP tool name are read inside a BC, where the surrounding path supplies the aggregate. A command class name escapes its namespace: its `_COMMAND_NAME` is a flat label written into the event envelope's `command_name`, the OTel span name, and the idempotency cache key, where every slice label shares one namespace and nothing around the string says which BC produced it. A qualifier the reader can recover from context is redundant; a qualifier the reader cannot recover is load-bearing.

URLs use the BARE verb when the path scope already implies the subject:

```
GOOD: slice = enter_thing_maintenance/, command = EnterThingMaintenance,
      MCP tool = enter_thing_maintenance,
      URL = POST /things/{thing_id}/enter-maintenance
BAD:  URL = POST /things/{thing_id}/enter-thing-maintenance
```

### Multi-segment action paths

When an endpoint manipulates a sub-resource on its parent, the URL nests as `/{parent-id}/{sub-resource}/{verb}`. The noun-resource segment groups related actions; the verb terminates the path.

This nesting is reserved for sub-resources that have multiple actions or own a meaningful name independent of the parent. Single-action endpoints stay flat. Multi-word verb-preposition URL segments are banned; the noun-then-verb shape is the standard.

## Code identifier carve-outs

Each is a deliberate departure from a rule that holds elsewhere, and each is enforced by an architecture fitness test so a future rename does not undo it by accident.

### Boolean fields use bare adjectives

The shape is `<adjective>: bool`, not `is_<adjective>: bool`. The reader's "is" comes from the field-access read-aloud (`thing.propagates_to_children`), not from a prefix that doubles the verb.

The `is_` / `has_` / `can_` prefix style is reserved for derived predicates: computed properties or helper functions that ask a yes-no question. A function `def is_active(state: Thing) -> bool` is the canonical case. The prefix style does not migrate onto stored field declarations.

### Cannot-transition errors are per-verb, not collapsed

When an aggregate exposes multiple verbs that all reject from the same source-state set, each verb gets its OWN cannot-transition error class: `<Aggregate>Cannot<Verb>Error`, not a single `<Aggregate>CannotTransitionError` keyed on a `requested_transition: str` field.

The verb name in the class IS the diagnostic. `except ThingCannotActivateError:` reads better than `if e.requested_transition == "activate":`, and handler-side mapping to HTTP 409 keys off `isinstance`, not a string field. The transition-name string is duplicate information the call site already knows.

Carve-out: when the aggregate has only ONE such verb and no foreseeable second, a bare `<Aggregate>CannotTransitionError` is acceptable. Promote to per-verb the moment a second transition slice lands.

### `Marked<Status>` events carry an asserted status

Event classes follow `<Aggregate><PastParticiple>` except where a status is asserted rather than achieved: `<Aggregate>MarkedUnavailable`. The `Marked` prefix says a status was asserted; who or what asserted it is a `trigger` payload field, not part of the class name. A monitor-driven path reuses the same classes with a different trigger value rather than introducing a parallel event family.

### Reversible-pause verbs split by entity kind

The reversible-pause verb is `suspend` on authorization and grant aggregates, and `hold` on execution, process, and container aggregates. Both share one recovery verb, `resume`.

- **Grant-shaped aggregates use `suspend` with the state value `Suspended`**, paired with a terminal `revoke` or `deprecate`. This is the shape the wider world uses for licenses, accounts, and credentials.
- **Execution, process, and container aggregates use `hold` with the state value `Held`**, paired with an execution terminal such as `abort`, `stop`, or `close`. This is the shape process and job control use.

The discriminator is the entity kind and its terminal verb, not the PackML operator-versus-condition axis. If an aggregate ever gains genuine condition-driven auto-resume, revisit: `suspend` would then be the standards-correct word for the auto case.

### Cross-aggregate edits use `*To*` / `*From*`

`ThingAddedToGroup` / `ThingRemovedFromGroup` carry the preposition because the action targets a sibling aggregate, not the thing itself. A bare past-participle would read as if the thing was created or deleted; the preposition makes the cross-aggregate scope explicit.

### Projection tables use `proj_<bc>_<aggregate>_<rowtype>`

`<rowtype>` names the stored relation: `_summary` (one row per aggregate), `_membership` (join row), `_children` / `_consumers` (reference row), `_ratings` (multi-row per aggregate). It names the persisted relation, not a usage pattern; `_lookup` is not a relation noun.

When the BC contains a single aggregate AND the BC name equals the aggregate name, the redundant prefix is dropped: `proj_<aggregate>_<rowtype>`. In a multi-aggregate BC, a non-eponymous aggregate takes the full shape while the eponymous one keeps the dropped-stutter carve-out. When the BC contains a single aggregate but the BC name differs from the aggregate name, the BC prefix stays, for grep symmetry with multi-aggregate BCs.

### UUID collection fields carry `_ids`

`frozenset[UUID]` fields name what they point at and carry the `_ids` suffix: `part_ids`, `allowed_credential_ids`. Unenforced today; the check belongs with the first aggregate carrying such a field.

A field whose bare name is a standard vocabulary term from an external ontology the project intends to export to may drop the suffix, via a named carve-out in that test's registry. Do not extend the bare-plural shape outside such a vocabulary.

### Self-referential parent pointers use `parent_id`

Self-referential parent pointers on aggregate state use the field name `parent_id` with type `<Aggregate>Id | None`. The aggregate's own module namespace already disambiguates the target type, so the verbose `parent_<aggregate>_id` and `part_of_<aggregate>_id` forms are forbidden: `Thing.parent_id`, not `Thing.parent_thing_id`.

Cross-aggregate parent pointers keep their qualifier, because the qualifier is NOT the aggregate's own name: `Thing.parent_group_id` references a Group. Unenforced today; the check belongs with the first self-referential aggregate.

## Documentation

Docstrings carry intent. Comments carry hidden constraints. Test names carry scenarios. Everything else is noise.

### Which home a claim belongs in

There are two places a rule can be written down, and writing it in both is how
they drift. The split:

| | Owns | Example |
| --- | --- | --- |
| `docs/reference/` | The RULE. What the convention is, why it exists in general, what the anti-patterns are. | "A port is a Protocol, and its adapters are named for the technology behind them." |
| A docstring | The SITE. Why THIS module implements the rule the way it does, and what is non-obvious here. | "This store is one instance per process, because more than one BC appends through it." |

A docstring that restates the general rule is duplication. Link instead: open by
naming the convention page, then explain only what this seam adds.

**A fact may appear in both; a rationale may not.** The idempotency cache key
is stated in `patterns.md` and again on the port, because a reader of the port
must see the contract without leaving the file. What must NOT appear twice is
the reason for it: two explanations of one decision become two decisions the
first time someone edits one.

When they do conflict, `docs/reference/` wins and the docstring is the bug.
It is the page a reader consults before writing code, so a stale rule there
misleads earlier and wider than a stale docstring does.

### Do not describe machinery that does not exist

Write a rule as a rule. Do not write it as a description of enforcement unless
the enforcement is there: "enforced by `test_x.py`" is a claim a reader will
check by reading the sentence, not the directory.

This repository carried 20 such claims from the project its chassis came from,
naming fitness tests that exist there and not here, and one of them helpfully
explained the silence of the others. A rule known to be unenforced is useful.
A rule falsely believed to be enforced is worse than no rule, because nobody
looks twice at it.

The same applies to evidence. A measurement belongs to the system that
measured it; quoting a sibling project's numbers to justify a decision here
makes the reasoning unfalsifiable, since nothing in this tree can reproduce
or refute them.

No emoji anywhere in source: comments, docstrings, log strings, error messages, `Field(description=...)`. Emoji in source is a documented LLM tell that accumulates as noise across reviews. This mirrors the no-em-dash rule applied to prose.

### Citing an external source

Two different things get called a citation, and they need different links.

**Reading a source: link the moving ref.** A navigational link wants whatever that page says today, so link `main`, `HEAD`, or `/en/latest/`. Pinning a navigational link sends the reader to a stale copy, which is worse than no link.

**Sourcing a value: identify the version.** When a number, an address, a serial, or a step order is recorded because an external artifact said so, the citation has to say which state of that artifact. Otherwise the value silently stops matching its own source the next time the source changes, and nothing here notices. Use a commit SHA for a repository, and for a page with no addressable version, keep the readable link and name the date the value was folded from it beside the value.

The distinction is not about how important the source is. It is about whether this project is repeating a claim. A record whose provenance means "whatever that file says now" is not a record.

Verify before pinning: read the source at the ref you are about to cite. A wrong pin is more misleading than a moving one, because it looks checked.

### Docstrings

Every public module, class, function, and method gets a docstring. Style is prose, not Sphinx.

- **One imperative summary line.** Single-line docstrings stay on one line and end with a period. Carve-out: a port `Protocol` class describes a seam, not an action, so its summary may lead with a role noun-phrase.
- **Prose body when more is needed.** Blank line after the summary, then narrative paragraphs. Use Markdown subheaders (`## Section`) for distinct concerns.
- **Domain vocabulary matches the [glossary](glossary.md).** A slice handler is a handler, not an endpoint. An aggregate is an aggregate, not a model. An evolver is an evolver, not a reducer.
- **Cross-references**: backticks for in-module symbols; a dotted path for cross-BC symbols (`keeper.infrastructure.slices.evolver.require_state`).

#### A docstring may not name code or files that do not exist

Backticks mean "this is a symbol". A reader who cannot find a backticked
name has no way to tell a name they have missed from a name that is not
there, so every dangling reference costs a search that ends in nothing.

Two fitness tests in `test_docstring_references_resolve.py` enforce this: a
backticked CamelCase name must be defined somewhere in `src/` or `tests/`,
and a cited file path must exist in the repository.

The tests admit two declared exceptions, each a named frozenset:

| | For | Example |
|---|---|---|
| `EXTERNAL_NAMES` | Real, defined outside this repository | `PoolConnectionProxy` (asyncpg) |
| `PROSPECTIVE_NAMES` | Real nowhere, deliberately | `Handler`, the shape a future slice should adopt |

`PROSPECTIVE_NAMES` exists because naming a thing before it exists is a
legitimate move: telling a future author what to call something, standing
in for a per-aggregate type inside a worked example, or rejecting an
alternative by name. Each entry still costs a line, so adding one is a
decision rather than a way past the check.

Neither test can see a wrong explanation of a real symbol. They catch the
cheaper failure, which is prose that refers to nothing at all. This
repository had 118 such references after the chassis was copied.

Use a word instead of a symbol when you mean a word: an `Adapter` suffix is
a string, not a class, and the backticks claim otherwise.

**Role-type templates** (copy rather than improvise):

| Role | Module summary | Function summary |
| --- | --- | --- |
| Evolver | "Evolver: replay events to reconstruct `<Aggregate>` state." | `evolve()`: "Apply one event to the current state." / `fold()`: "Replay a stream of events from the empty initial state." |
| Read repo | "Read repository for the `<Aggregate>` aggregate." | `load_<aggregate>()`: "Load and fold a `<Aggregate>`'s event stream into current state." |
| Slice file header | "<role> for the `<slice>` slice." | n/a |

**Anti-patterns:**

- Do not use `Args:` / `Returns:` / `Raises:` sections. Type annotations are the parameter contract; raised exceptions belong in prose when non-obvious.
- Do not restate the type signature in prose.
- Do not write `>>>` doctest examples. The tests are external.
- Do not name a phase, iteration, or audit in a docstring. Those rot. The current code is what is true; ordering lives in git history. Name the precedent itself, not the phase that shipped it.

### Comments

Default to none. Well-named identifiers carry WHAT.

Add a `#` comment only when the WHY is non-obvious: a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a reader. State the constraint, not the history.

**Anti-patterns:**

- Do not narrate WHAT the next line does. The code says that.
- Do not annotate the current task, fix, or caller. Git log and the PR description are the right home.
- Do not leave dead-code markers (`# was`, `# previously`, `# old`). Delete the dead code.
- Do not leave `# TODO`, `# FIXME`, `# HACK` without an owner and a trigger. File an issue or drop it.
- Do not use `# noqa: <code>` without a trailing comment explaining the suppression.
- Do not draw section dividers. The role-typed file layout, one aggregate per file and one slice per directory, already provides navigation.

### Tests

Test names carry scenarios. Per-test docstrings stay rare.

- **`test_<subject>_<scenario>_<expectation>`** is the naming convention. Long is fine.
- **Property-based tests document the property**, not the test shape. The `@given` body is the test; the docstring is the invariant being verified.
- **Architecture tests document the rule, the rationale, and the exception.** They are the structural guardrails; a future contributor needs to know why each rule exists.
- **Fixture docstrings only when non-obvious.** Per-worker Postgres containers, kernel-construction sites, and similar subtleties get one paragraph in `conftest.py`. Simple fixtures stay bare.
