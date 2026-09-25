# Security Policy

## Supported versions

The keeper is pre-1.0 and under active development; APIs and schema are subject to
change. Only the `main` branch receives security fixes. There are no LTS lines.

## Reporting a vulnerability

Please **do not** open a public issue for security vulnerabilities.

Use **GitHub's private vulnerability reporting** for this repository:

1. Go to the [Security tab](https://github.com/open-cora/keeper/security) of the repo.
2. Click **Report a vulnerability**.
3. Fill in the form with as much detail as you can:
   - the affected component (port, adapter, event store, migration, etc.)
   - the impact (data exposure, privilege escalation, denial of service, etc.)
   - reproduction steps or a proof-of-concept
   - the commit hash you tested against

You will receive an acknowledgement within **5 business days**. We aim to issue a
fix or a public advisory within **30 days** of acknowledgement, depending on
severity and complexity.

## Scope

In scope:

- The keeper application itself: handlers, ports, adapters, event store, API
  surfaces (REST + MCP), authentication wiring, authorization port.
- Migrations and database role configuration in `infra/atlas/`.
- CI, build, and tooling in `.github/workflows/` and `Makefile`.

Out of scope:

- Vulnerabilities in upstream dependencies; report those upstream.
- Misconfiguration of a downstream deployment that does not front the API with a
  verifying proxy. The `X-Principal-Id` header trust contract is documented in
  [docs/reference/runtime.md](docs/reference/runtime.md); deploying without a
  verifying proxy is a deployment misconfiguration, not an application
  vulnerability.
- Issues that require an authenticated principal already holding sufficient
  privilege. Those are bugs; please open a normal issue.

## Hardening notes

The production gates are:

- `DATABASE_URL` connects as the `keeper_app` role: the `events` table is
  INSERT-only (UPDATE / DELETE / TRUNCATE revoked). Migrations run as the
  database owner.
- `REQUIRE_AUTHENTICATED_PRINCIPAL=true`
- `APP_ENV=prod`, which refuses to boot if the above flag is not set.

A verifying proxy in front of the API is mandatory in production: it must
authenticate the caller, strip any client-supplied `X-Principal-Id` header, and
set the verified principal id.
