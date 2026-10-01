# Deploying the keeper

Installs the keeper and its database as `systemd --user` services, with no
root, no system package and no Docker.

```bash
CORA_ROOT=/local/cora ./install.sh
```

Re-running it is the intended way to deploy a new revision. It never
regenerates a password that exists and never touches an initialised data
directory.

## What decides the shape of this

Three properties of the host, each measured rather than assumed, and each
responsible for a choice that would otherwise look arbitrary.

**There is no root.** Supervision is `systemd --user`, which stops every
service at logout unless lingering is enabled for the account. An
administrator has to run `loginctl enable-linger <account>` once; nothing
here can.

**There is no Docker, and podman is rootless.** Rootless podman needs a
`subuid` and `subgid` range for the account, or an image cannot map its own
internal users and Postgres fails during initdb. The range is keyed by
numeric uid in `/etc/subuid`, not by name, which is worth knowing before
concluding an account has none.

**`$HOME` is NFS and shared.** Every machine the account can log into mounts
it, so a unit file written here is visible on all of them. Each unit
therefore carries `ConditionHost`, and `install.sh` fills it from the host's
own `hostname` because the spelling is not uniform: some machines answer with
a fully qualified name and some with a short one, and systemd compares
against whichever the host gives.

Everything with state lives on local disk for the same reason inverted.
Postgres over NFS is a file-locking hazard even with one writer, and two
hosts reaching one cluster is data loss rather than a warning.

## Why plain units and not quadlet

Quadlet is the better tool and this deployment cannot use it. It always
passes `--cgroups=split`, which requires cgroups v2. A host on v1 cannot
create a cgroup for a rootless container, so podman exits 126 with a
permission error against `/sys/fs/cgroup` before the image starts. A plain
unit passes no cgroup flag and runs.

The failure is worth recognising because it looks like a podman problem and
is a kernel one. Check with `stat -fc %T /sys/fs/cgroup`, and prefer a
`.container` file on any host that reports `cgroup2fs`.

## Who a caller is

`issue_tokens.py` mints an EC signing key, writes the public half as a JWKS,
and signs one long-lived bearer token per caller. `install.sh` runs it, sets
`REQUIRE_AUTHENTICATED_PRINCIPAL`, and serves the JWKS on loopback for the
keeper's own verifier to fetch. The `X-Principal-Id` header stops being
believed at that point.

This is not an identity provider. There is no discovery document, no token
endpoint, no refresh and no revocation. It is enough because the roster is
four beamlines and a thinker, known in advance, and because the verifier
asks only for a JWKS and a signature. Revoking means re-minting the key and
reissuing five files.

**Each token goes to exactly one caller**, into that account's own home at
mode 600, and nothing here should ever be copied to more than one beamline.
The private key never leaves the keeper's host.

### What a subject is called

A subject is `<role>-<beamline>` for anything that runs at a beamline, and
the bare role for anything central. So `conductor-19-bm` and
`reporter-19-bm`, and `thinker` with no suffix. The beamline half is spelled
the way `beamlines/` spells it: `2-bm`, `7-bm`, `19-bm`, `32-id`.

The order is not a preference. That string already names the configuration,
the log and, through `{subject}.token`, the credential itself, so a subject
in the other order would be the one artifact of four spelled differently
from the rest, and an operator holding `reporter-2-bm.toml` would have to
transpose it to find the token.

Splitting a beamline into two subjects buys attribution and nothing else.
It is not a security boundary: both processes run in the same account from
the same home, so whoever can read one token can read the other. There is
no revocation to be granular about either.

**Renaming a subject mints a different principal.** `actor_id` is a `uuid5`
of the subject, so `19-bm` and `conductor-19-bm` are two principals and
everything already recorded stays attributed to the first. Provenance
splits at the rename, which is why it is worth doing once rather than
drifting into it.

`subject_bindings` is a list, so both can be bound at once. The migration
is to add the new subjects, swap each configuration in its own time, and
drop the old ones at a later restart. Nothing is down and there is no flag
day.

**The running keeper predates this.** It binds `2-bm`, `7-bm`, `19-bm`,
`32-id` and `thinker`, one per beamline with no role in the name, so a
beamline's conductor and its reporter share a subject today. That is why
the examples elsewhere in this file still name `2-bm.token`. Changing it
needs a keeper restart, which every beamline feels, so it waits for a
restart that was going to happen anyway.

`install.sh` verifies both directions itself and refuses to finish if an
anonymous request is answered, because a check that only tries the valid
case cannot tell an enforcing deployment from an open one. That exact
mistake shipped an unauthenticated API here once already.

```bash
curl --cacert "$CORA_ROOT/etc/tls/ca.crt" -o /dev/null -w '%{http_code}\n' \
  "https://$HOST:8443/devices"
curl --cacert "$CORA_ROOT/etc/tls/ca.crt" -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(cat "$CORA_ROOT/etc/tokens/2-bm.token")" \
  "https://$HOST:8443/devices"
```

401 then 200. `/health` answers without a token on purpose, so a liveness
check needs no credential.

## The wire

`issue_tls.py` mints a small CA and a server certificate for the name
clients dial, and uvicorn terminates TLS itself, so there is no proxy, no
privileged port and no root. **The API is the only thing reachable off the
host.** The database and the JWKS stay on loopback because nothing else
reads them.

There is no plaintext port, deliberately. A token sent in the clear is a
token anyone on the path can lift and replay, so offering both would undo
the reason for having either.

A private CA rather than a public one because the keeper answers on a
facility address with no inbound path from the internet, so an HTTP or DNS
challenge cannot complete, and a search of the host found no internal
issuing service. A CA plus a leaf rather than one self-signed certificate so
that reissuing the server key never means touching every client again.

**Each beamline needs exactly two files**, and no more: its own token, and
`ca.crt` so it can verify the server. Neither is a secret shared with any
other beamline, and the CA private key signs nothing else and never leaves
the keeper's host.

**TLS and the token answer different questions and neither should grow into
the other.** TLS makes the wire private and proves the server; the token
says which beamline is calling. Swapping this CA for a facility one later is
a certificate on the server and a path on each client, and changes no part
of the design.

The certificate expires. 825 days for the leaf, ten years for the CA, and
reissuing the leaf is deleting it and running `install.sh` again.

## What it is not

**No authorization policy.** `APP_ENV` is set to a value that is not a
production tier, which is accurate rather than a placeholder: a production
tier refuses to boot without a policy, and the first policy has to be
authored through the API before anything can be authorized against it.
Authentication does not wait for that, which is why it is on here and the
tier is not.

**No backups.** The database is a bind mount at `$CORA_ROOT/pgdata`, so
`pg_dump` through the container is the whole story for now.

## Operating it

```bash
systemctl --user status keeper.service keeper-postgres.service
journalctl --user -u keeper.service -f
tail -f "$CORA_ROOT/log/keeper.log"
podman logs -f keeper-postgres
```

Deploy a revision by updating the source and running `install.sh` again. It
restarts each service rather than relying on `enable --now`, which is a no-op
against something already running and would otherwise write a new
configuration to disk that never reaches the process.

Starting the database over needs podman, because `:U` chowned the directory
to a subordinate uid the account cannot remove directly:

```bash
systemctl --user stop keeper.service keeper-postgres.service
podman unshare rm -rf "$CORA_ROOT/pgdata"
./install.sh
```

## The files

| | |
| --- | --- |
| `install.sh` | preflight, secrets, virtualenv, tokens, certificate, units, migrations, start |
| `issue_tokens.py` | the signing key, the JWKS, one token per caller |
| `issue_tls.py` | the private CA and the server certificate |
| `keeper-postgres.service.in` | the database, a rootless container |
| `keeper-jwks.service.in` | the public key, served for the verifier |
| `keeper.service.in` | the HTTP surface |

The templates carry `@NAME@` placeholders and name no host, so the tracked
copy shows the shape and the installed copy shows the deployment.
