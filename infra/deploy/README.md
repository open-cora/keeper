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

Verify both directions after installing, because a check that only tries the
valid case cannot tell an enforcing deployment from an open one:

```bash
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/devices
curl -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $(cat "$CORA_ROOT/etc/tokens/2-bm.token")" \
  http://127.0.0.1:8000/devices
```

401 then 200. `/health` answers without a token on purpose, so a liveness
check needs no credential.

## What it is not

**No TLS, and no authorization policy.** `APP_ENV` is set to a value that is
not a production tier, which is accurate rather than a placeholder: a
production tier refuses to boot without an authorization policy, and the
first policy has to be authored through the API before anything can be
authorized against it. Authentication does not wait for that, which is why
it is on here and the tier is not.

That missing TLS is the whole reason everything binds `127.0.0.1`. Reach the
API through a tunnel:

```bash
ssh -N -L 8000:127.0.0.1:8000 <host>
```

**Widening the bind address and terminating TLS are one change, never two.**
A token over plain HTTP off this host is a token anyone on the path can
lift and replay.

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
| `install.sh` | preflight, secrets, virtualenv, tokens, units, migrations, start |
| `issue_tokens.py` | the signing key, the JWKS, one token per caller |
| `keeper-postgres.service.in` | the database, a rootless container |
| `keeper-jwks.service.in` | the public key, served for the verifier |
| `keeper.service.in` | the HTTP surface |

The templates carry `@NAME@` placeholders and name no host, so the tracked
copy shows the shape and the installed copy shows the deployment.
