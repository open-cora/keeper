# Running one

This page is for whoever has to stand the keeper up and keep it running. It
covers what it needs, how to start it locally, and the one sequence that has to
happen in the right order or the deployment locks itself out.

## What it needs

Postgres, and nothing else. No message broker, no cache, no other service. The
keeper talks to its database and answers requests; everything else in the system
dials in to it.

Two database users, not one, and which is which is worth getting straight
because the names do not help. `keeper` owns the schema and is what migrations
run as; it may change anything, including the event log. `keeper_app` is what
the running server connects as; it may read events and add events, and the
schema revokes its UPDATE, DELETE and TRUNCATE.

That separation is what makes the history append-only in fact rather than by
agreement: the record is sealed by a database grant rather than by the
application's own SQL being careful. Above the production tier the keeper
refuses to start when the role it connected as can rewrite events, so a
deployment cannot give the guarantee up by editing a connection string.
Below that tier it logs a warning instead, because local development connects
as the owner in order to run the migrations.

## Starting one locally

```bash
make install        # install dependencies
make db-up          # start Postgres on host port 5433
make migrate-apply  # create the schema
make dev            # the API, on http://localhost:8000
```

Port 5433 rather than the usual 5432, so it does not clash with a Postgres you
already have running.

Four addresses are worth knowing:

```
   GET  /health    is the process alive
   GET  /readyz    can it serve a correct request
   GET  /events    the log, from a cursor, oldest first
   POST /mcp       the same operations, for a machine
```

## Reading the log

`GET /events` hands back committed events in the order they committed,
from a cursor the caller holds, and `wait` holds the request open until
something lands rather than answering empty. It is how a terminal, a
dashboard or an alerting path watches what is happening without polling.

```bash
curl -s "$KEEPER/events?limit=20"
curl -s "$KEEPER/events?after=$CURSOR&wait=30"
```

It is not on the surface page with the other operations, because it
belongs to no bounded context: it reads the table all of them write into.
For the same reason it has no MCP tool. An agent asking what is happening
has every context's reads already, and those answer with current state.

Two grants decide what comes back. `ReadEventLog` returns every stream
behind a read that all principals hold, and `ReadFullEventLog` adds the
Actor and Policy streams, which are the administrator's for the same
reason `GetActor` and `GetPolicy` are. Nothing is granted by default.

**The log cannot be narrowed to one beamline.** Three events name a
beamline and each opens a stream; nothing that follows one names it. So a
reader of the log reads the facility, and whether that is acceptable is a
question to answer before granting it rather than after.

`/health` checks nothing and is meant to. Every dependency it could check is one
a restart cannot fix, so a health probe that checked the database would restart
the process into a database outage and turn one problem into a crash loop.
`/readyz` is the probe that reports dependencies.

Locally, nothing is locked down: there is no rulebook configured, so every
request is allowed and an unauthenticated one runs as a built-in fallback
identity. That is the development posture, and the next section is how you leave
it.

## Turning authorization on, in this order

This is the part to read twice. Getting the steps the wrong way round leaves a
deployment nobody can fix through the API.

```
   1.  register the administrator            POST /actors
       keep the id it returns

   2.  write the rulebook, naming that id    POST /policies
       it must permit at least GrantPolicyPermission
       keep the id it returns

   3.  set AUTHZ_POLICY_ID to the policy id
       set REQUIRE_AUTHENTICATED_PRINCIPAL=true
       set APP_ENV to anything but local, test or dev
       point DATABASE_URL at keeper_app

   4.  restart
```

**Why the order matters.** A request is allowed only when two things are true at
once: the rulebook permits it, and there is an active actor on record for
whoever is asking. Write the rulebook first and it names a principal that Access
has never heard of, so it authorizes nothing, and the command that would put
that right is one of the ones now being refused.

**Why it is one-way.** The fallback identity cannot be granted anything, on
purpose, so once a real rulebook is in force an unauthenticated request is
refused everything. You author the first policy before switching over, never
after.

**Why the rulebook must permit granting.** A policy that permits nobody to
change it can only shrink. Whoever may grant can always grant any other
permission back, so every other loss is recoverable and that one is not. The
keeper refuses to write a policy without it.

If `AUTHZ_POLICY_ID` points at a policy that does not exist, every request is
refused and no request can repair it. That is deliberate: a typo in one
environment variable becomes an outage you can see rather than an open door you
cannot.

Both of these are fixed the same way, by changing the environment and
restarting. There is no way back in through the API, and that is the point.

## What refuses to start

On a production `APP_ENV`, which means anything other than `local`, `test` or
`dev`, the keeper will not boot if:

```
   authentication is not required
   no rulebook is configured, or the configured one is the permissive stand-in
   the database role it connects as can rewrite events
```

One more refusal is not about the tier and fires in every environment: the
keeper will not boot if the database schema is not the version this build
expects.

That one has an escape hatch. `ALLOW_SCHEMA_VERSION_MISMATCH=true` boots
anyway with reads working and every write refused, so a restored database can be
inspected without risking a history that cannot be corrected afterwards. It
protects the event log and not every table, so scope it honestly.

Everything else is a refusal with no override, because each alternative is a
system that looks like it is running and is not doing what somebody thinks.

## The settings that matter

| Setting | Default | What it does |
| --- | --- | --- |
| `APP_ENV` | `local` | Which posture to run in. Anything but `local`, `test` or `dev` turns the refusals above on, so a name this list does not know is treated as real. |
| `DATABASE_URL` | local Postgres on 5433 | Where the database is, and which user to be. |
| `AUTHZ_POLICY_ID` | unset | The rulebook to authorize against. Unset means allow everything. |
| `REQUIRE_AUTHENTICATED_PRINCIPAL` | `false` | Whether an unidentified request is refused or runs as the fallback identity. |
| `IDENTITY_PROVIDERS` | none | Token issuers to verify against. With none configured, identity comes from a header a proxy must set. |
| `ALLOW_SCHEMA_VERSION_MISMATCH` | `false` | Boot on the wrong schema, reads only. |
| `LOG_LEVEL` | `INFO` | |
| `OTEL_EXPORTER` | `none` | `none`, `console` or `otlp`. |
| `MAX_REQUEST_BODY_SIZE_BYTES` | 1 MiB | Requests over this get a 413. |

Full detail on each, and on what is wired where, is in
[Runtime](reference/runtime.md).

## Identity, and the header you must not trust

With no token issuers configured, the keeper reads who is calling from an
`X-Principal-Id` header. Anything can send that header, so a production
deployment must sit behind a proxy that verifies the caller, strips whatever
header the client sent, and sets the verified one itself.

Configure token issuers instead and the keeper verifies bearer tokens itself,
which is the arrangement that does not depend on a proxy being configured
correctly.

## Reading the logs

Every operation logs when it starts and again when it is allowed or refused, so
a refused request leaves a line naming the caller and the operation they asked
for. That pair is how you find a permission with a typo in it: the operation a
caller actually sent shows up in the denials, and a permission naming an
operation that does not exist never shows up at all.

Field names, and the shape of every line, are in
[Runtime](reference/runtime.md#logging).

## Migrations

```bash
make migrate-status   # what has been applied
make migrate-apply    # apply what has not
make migrate-new      # start a new one
```

Migrations only go forwards. There is no down step, because the event log cannot
be rewritten and a migration that claimed to undo itself would be lying about
the one table that matters.
