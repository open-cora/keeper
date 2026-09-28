# Running one

This page is for whoever has to stand the keeper up and keep it running. It
covers what it needs, how to start it locally, and the one sequence that has to
happen in the right order or the deployment locks itself out.

## What it needs

Postgres, and nothing else. No message broker, no cache, no other service. The
keeper talks to its database and answers requests; everything else in the system
dials in to it.

Two database users, not one. Migrations run as the owner, which may change the
schema. The application runs as `keeper_app`, which may read and add rows to the
event log and may not change or delete them. That separation is what makes the
history append-only in fact rather than by agreement, and the production check
below refuses to start without it.

## Starting one locally

```bash
make install        # install dependencies
make db-up          # start Postgres on host port 5433
make migrate-apply  # create the schema
make dev            # the API, on http://localhost:8000
```

Port 5433 rather than the usual 5432, so it does not clash with a Postgres you
already have running.

Three addresses are worth knowing:

```
   GET  /health    is the process alive
   GET  /readyz    can it serve a correct request
   POST /mcp       the same operations, for a machine
```

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
       set APP_ENV to a production value
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

On a production `APP_ENV`, the keeper will not boot if:

```
   authentication is not required
   no rulebook is configured, or the configured one is the permissive stand-in
   the database schema is not the version this build expects
```

The last one has an escape hatch. `ALLOW_SCHEMA_VERSION_MISMATCH=true` boots
anyway with reads working and every write refused, so a restored database can be
inspected without risking a history that cannot be corrected afterwards. It
protects the event log and not every table, so scope it honestly.

Everything else is a refusal with no override, because each alternative is a
system that looks like it is running and is not doing what somebody thinks.

## The settings that matter

| Setting | Default | What it does |
| --- | --- | --- |
| `APP_ENV` | `local` | Which posture to run in. A production value turns the refusals above on. |
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
