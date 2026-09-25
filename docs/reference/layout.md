# Layout

*BC structure, slice shapes, imports, shared code.*

Two axes on purpose: aggregates own the data shape so the domain stays explicit, slices own the use cases so a feature lives in one folder. Modular Monolith on the macro side, Vertical Slice on the micro. Keeping both stops the codebase from collapsing into either pure DDD or pure feature-folders.

## Package layering

```
keeper/
├── shared/           pure value objects and helpers; zero keeper.* imports
├── infrastructure/   ports, adapters, composition root, event-sourcing machinery
├── api/              FastAPI app, middleware, readiness, MCP mount
└── <bc>/             one package per bounded context
```

The contract is declared in `apps/keeper/tach.toml` and checked by `uv run tach check`:

- `shared` depends on nothing.
- `infrastructure` depends only on `shared`.
- A BC depends on `shared` and `infrastructure`, plus any sibling BC's `aggregates.*` namespace it names.
- `api` depends on every BC.

A BC may reach into a sibling only through that sibling's `aggregates.*` namespace, which is the read-side public surface. Never through `features.*`.

**Read tach.toml as the doors that have been cut, not as a map of what depends on what.** It constrains imports, and imports are only one of several ways one BC comes to depend on another. A `Protocol` declared in `infrastructure.ports`, implemented by one BC's adapter and consumed by another, leaves no import to constrain: both sides name only `infrastructure`, which every module does. An event subscription names its producer with a string. Where the import graph and the dependency graph differ, the dependency graph is the larger one.

`tests/architecture/test_tach_edges_are_used.py` fails on an entry no source file takes up, so a permission whose reason has gone away does not quietly stay. It found one on its first run.

## BC layout

```
keeper/<bc>/
├── __init__.py                       # re-exports public BC surface
├── _bootstrap.py                     # BC-internal constants
├── _<aggregate>_update_handler.py    # update-handler factory hoist (when n>=3 update slices share scaffolding)
├── errors.py                         # BC-application-layer errors
├── routes.py                         # register_<bc>_routes(app)
├── tools.py                          # register_<bc>_tools(mcp, *, get_handlers)
├── wire.py                           # <Bc>Handlers bundle + wire_<bc>(deps)
├── aggregates/
│   └── <aggregate>/
│       ├── state.py                  # state + value objects + domain errors
│       ├── events.py                 # event classes + union + payload helpers
│       ├── evolver.py                # evolve(state, event) + fold(events)
│       ├── read.py                   # load_<aggregate> (fold-on-read)
│       ├── <row>.py                   # projection row + the read port over it
│       └── <vo_module>.py            # aggregate-internal value objects
├── adapters/                         # implementations of ports, this BC's own or a shared one
│   └── <tech>_<port>.py              # <Tech><Port>, no Adapter suffix
├── projections/
│   ├── register.py                   # register_<bc>_projections(registry, deps) entry point
│   └── <name>.py                     # read-side projection (consumed by list_* queries)
└── features/
    ├── <verb>_<aggregate>/           # one folder per COMMAND
    │   ├── command.py
    │   ├── decider.py
    │   ├── handler.py
    │   ├── route.py
    │   ├── tool.py
    │   └── context.py                # OPTIONAL: cross-aggregate pre-load before pure decider
    └── get_<aggregate>/              # one folder per QUERY (no decider)
        ├── query.py
        ├── handler.py
        ├── route.py
        └── tool.py
```

Each slice's `__init__.py` re-exports its public surface so callers write `register_thing.bind(deps)`. Events live in the aggregate folder, not the slice: they are intrinsic facts about the aggregate's history.

### Three slice shapes

Three shapes, to be pinned by a slice-contract fitness function once the first slice exists (not written yet, because it would range over nothing):

1. **Command slice**: `__init__, command, decider, handler, route, tool`. Default for state-changing operations that fold through a pure decider.
2. **Query slice**: `__init__, query, handler, route, tool`. No decider; reads from the aggregate or a projection.
3. **Entry-append slice** (`append_<entry>`): `__init__, command, handler, route, tool`. No decider; the handler writes directly to a typed entries store via a per-category port. This shape is indistinguishable from a malformed command slice by file list alone, so whatever pins the contract will need an explicit allowlist of which slices are deliberately decider-free.

### Optional slice files

`context.py` holds a slice-local cross-aggregate pre-load, used when a decider needs sibling-aggregate state. The decider for a context-using slice takes a keyword-only `context: <X>Context` parameter immediately before `now`, where `<X>Context` is a frozen dataclass exported from the slice's `context.py`. The handler builds the context by loading the sibling aggregates and passes it to the pure `decide`; the decider itself never reads from a port.

**Signature-parity `_ = state` discard.** When a context-using decider's own aggregate state lives on the context (either the child is genesis, or the context carries the same state as `state`), the decider opens with `_ = state  # <reason>` to discard the parameter while keeping the signature aligned with single-stream deciders.

### The projection registrar

`register_<bc>_projections(registry, deps)` is the composition-root entry point for a BC's projections, and it lives in `projections/register.py`, inside the package it registers. Mechanical, present in every BC that has projections at all. `test_every_bc_is_mounted.py` requires the composition root to call it; that rule spent the whole baseline unable to fire, because it looked for a file the layout above never draws.

The BC's other three plug points are flat modules at the context root named for the call (`wire.py`, `routes.py`, `tools.py`). The fourth cannot use the matching name, because a module and a package cannot share a name inside one package, and the package is where the projections themselves belong. Rather than invent a filename for the context root, the registrar sits with the things it registers, which is the folder-names-the-subject, file-names-the-role shape already used under `aggregates/` and `features/`. The package's `__init__.py` re-exports it, so callers write the package either way.

The same applies to `register_<bc>_subscribers(registry, deps)`, which wires a BC's domain-event reactions into the same registry's subscriber bus. No BC has one yet; when one does, the registrar belongs with the reactions rather than in a flat module at the context root.

### BC-root extras

- `_<aggregate>_update_handler.py`: factory that hoists shared update-handler scaffolding when n>=3 update slices on the same aggregate share the pattern. **Offered, not mandated.** Execution took it to five slices, built the shell, measured, and reverted; read the next paragraph before reaching for it.
- `_<aggregate>_dtos.py`: BC-local DTO module re-exported from `routes.py` and `tools.py`, kept out of the slice folder when several read/write slices share the same projected shape.

#### Why Execution declined the update-handler hoist

Execution reached five update slices on its Run aggregate, well past the n>=3 threshold, built the shell and then removed it. That aggregate has since been retired and the five slices with it, so the shell has nothing left to wrap; the argument that decided it is kept here because the next context to reach three will have the same one.

The five handlers were byte-identical once names were erased, which is the textbook case for hoisting. But so were three of the other four files in those slices:

```
   duplicated across the five slices, structurally identical:

   route.py    336 lines  ████████████████   left alone
   handler.py  265 lines  ████████████       the hoist candidate
   tool.py     255 lines  ████████████       left alone
   command.py  142 lines  ██████             left alone

   decider.py  257 lines  five genuinely different decisions
```

Duplication between slices is the price of vertical slicing, not a defect. Paying it for routes, tools and commands while refusing it for handlers is arbitrary, and handlers are not even the largest of the four. The route and tool files are the interesting case: their code is identical and everything that differs is prose written for humans, the OpenAPI summary and the wording of each conflict. Hoisting a prose carrier means passing five strings into a factory and burying the API documentation inside a call.

Two things made declining cheap. The guard against a copied slice running its neighbour's gate lives in `test_handlers_authorize_their_own_command.py`, and it now follows either shape, so locality costs nothing in safety. And the shell's cost was not only the file: three generic protocols, the most abstract machinery in the tree, and a bounded-context root that stopped being purely compositional.

The observation that actually settled it: a handler's largest duplicated block is not the gate, it is the append-and-envelope block, and that block is identical in every command slice in every context. The shell was a local fix for a tree-wide pattern. If handler duplication is worth attacking, the moves that pay are at the chassis, next to `infrastructure/slices/envelope.py`, and they serve seventeen slices rather than five.

So: reach for this factory when the duplicated part is genuinely local to one aggregate. When it is the same shape every slice in the tree carries, it belongs in the chassis or nowhere.

### Private subpackages (BC-root reshape at scale)

Private `_*.py` modules stay flat at the BC root by default; the naming prefix (`_<aggregate>_<role>.py`) does the grouping. When a BC root crosses ~10 private modules and a cohesive cluster has emerged, carve that cluster into a private subpackage (`_<name>/` with a re-exporting `__init__.py`) so the root stays navigable.

Re-export the public surface so consumers import from the package, not the submodules. The canonical shared-pattern files (`_bootstrap.py`, `_<aggregate>_update_handler.py`) stay flat for cross-BC consistency.

**Capability-dependent handlers.** When a slice depends on an external capability that some deployments leave unwired, the handler bundle types the field as `Handler | None`, and the route guards on `None` and raises `HTTPException(503)` inline. The kernel does not synthesize a stub, because an unwired deployment should not look configured. This is the only documented exception to the rule that command-slice routes do not wrap handler calls. No capability in the baseline is optional in this way, so the pattern is stated ahead of its first use.

## Where shared code goes

| Scope | Home |
| --- | --- |
| One aggregate | `aggregates/<aggregate>/state.py`, split when over ~200 lines |
| Across aggregates in one BC | `<bc>/value_objects.py` or `<bc>/_shared/` |
| A port only one BC has any use for | `aggregates/<aggregate>/<noun>.py`, beside `read.py`, with its adapters in `<bc>/adapters/` |
| Across BCs, pure (zero `keeper.*` imports) | `keeper/shared/` |
| Across BCs, depends on ports or the kernel | `keeper/infrastructure/` |

Promote up only after three real usages with identical, stable invariants.
