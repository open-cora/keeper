#!/usr/bin/env bash
# Installs the keeper and its database as `systemd --user` services, with no
# root and no system-wide package.
#
# Re-running this is safe and is the intended way to deploy a new revision:
# it never regenerates a password that already exists and never touches a
# data directory that is already initialised.
#
# Three properties of the target host shape everything here, and all three
# were measured rather than assumed:
#
#   1. There is no root. Supervision is `systemd --user`, which needs
#      lingering enabled or every service stops at logout.
#   2. There is no Docker. Rootless podman runs the database, which needs a
#      subuid range or the image cannot map its own internal users.
#   3. $HOME is NFS and shared with every machine the account can log into,
#      so unit files are visible far beyond this host. Each one is pinned
#      with ConditionHost, and everything with state goes on local disk.
#
# The preflight below refuses rather than warns, because each of those
# failures is silent and late: lingering looks fine until the first logout,
# a missing subuid range surfaces as an unreadable initdb error, and an
# unpinned unit starts a second copy on the wrong machine.

set -euo pipefail

CORA_ROOT="${CORA_ROOT:-/local/cora}"
PG_PORT="${PG_PORT:-5433}"
API_PORT="${API_PORT:-8443}"

# The address the API answers on, and the only thing this deployment exposes
# beyond the host. TLS and the bearer token are what make that safe; the bind
# address is not a security control and is not treated as one.
API_BIND="${API_BIND:-0.0.0.0}"

# The name clients dial, which has to be a name the certificate carries.
# Defaults to this host's own idea of itself, the same source ConditionHost
# uses, so the two cannot disagree.
TLS_HOST="${TLS_HOST:-$(hostname)}"
JWKS_PORT="${JWKS_PORT:-8081}"

# One token per caller. The four beamlines run a conductor and a reporter
# under one account each, so they are one subject each; the thinker runs
# centrally under its own.
#
# `admin` runs nothing. It exists because a policy that nobody may change
# is refused at birth, so somebody has to hold GrantPolicyPermission, and
# putting that on a beamline would let that beamline grant itself anything.
# Its token is minted here and belongs with an operator rather than on the
# floor.
#
# The list is a default rather than something a caller passes, because a
# deploy that forgot a subject would drop that subject's binding from the
# identity provider and lock it out at the next restart.
#
# That is also why a subject added by hand to identity-providers.json does
# not survive: issue_tokens.py rewrites the file from this list on every
# deploy, so a binding not named here is gone at the next one. A new caller
# belongs in this line and nowhere else.
#
# `viewer` reads the event log and nothing else. It is central rather than
# per beamline, because the log cannot be fenced to one: the three events
# that name a beamline each open a stream and nothing that follows one names
# it, so whoever reads the log reads the facility.
SUBJECTS="${SUBJECTS:-2-bm 7-bm 19-bm 32-id thinker viewer admin}"

# A production-tier value, which arms four boot refusals: a real authorize
# adapter, authenticated callers, a configured policy, and a database role
# that cannot rewrite events. This script supplies all four, so a refusal
# here means one of them did not take rather than that the tier is wrong.
# Lowering it would switch the gates off and hide whichever one failed.
ENVIRONMENT="${ENVIRONMENT:-pilot}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ATLAS_DIR="${APP_DIR}/infra/atlas"

UNIT_DIR="${HOME}/.config/systemd/user"

# systemd matches ConditionHost against the host's own idea of its name,
# which is `hostname` with no flag. Some machines here answer with the FQDN
# and some with the short form, so asking is the only way to get it right.
DEPLOY_HOST="$(hostname)"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

echo "Installing the keeper on ${DEPLOY_HOST}"
say "app        ${APP_DIR}"
say "state      ${CORA_ROOT}"
say "ports      api ${API_PORT}, postgres ${PG_PORT}, both on loopback"
echo

echo "Preflight"
command -v podman >/dev/null 2>&1 || die "podman is not installed"
command -v uv >/dev/null 2>&1 || die "uv is not installed"
command -v atlas >/dev/null 2>&1 || die "atlas is not on PATH; migrations cannot be applied"

systemctl --user show-environment >/dev/null 2>&1 \
  || die "no systemd --user manager is running for this account"

linger="$(loginctl show-user "$(whoami)" -p Linger --value 2>/dev/null || echo no)"
[ "${linger}" = "yes" ] \
  || die "lingering is off, so services would stop at logout. Ask an administrator for: loginctl enable-linger $(whoami)"

grep -q "^$(id -u):" /etc/subuid && grep -q "^$(id -u):" /etc/subgid \
  || die "no subuid/subgid range for uid $(id -u), so rootless podman cannot start postgres"

case "$(df -T "${CORA_ROOT%/*}" 2>/dev/null | awk 'NR==2{print $2}')" in
  nfs*) die "${CORA_ROOT} would sit on NFS; postgres needs local disk" ;;
esac
say "ok"
echo

echo "Directories"
mkdir -p "${CORA_ROOT}"/{pgdata,etc,log} "${UNIT_DIR}"
chmod 700 "${CORA_ROOT}/etc"
say "ok"
echo

echo "Secrets"
PG_ENV="${CORA_ROOT}/etc/postgres.env"
APP_PG_ENV="${CORA_ROOT}/etc/keeper-app-db.env"
KEEPER_ENV="${CORA_ROOT}/etc/keeper.env"

if [ -f "${PG_ENV}" ]; then
  say "reusing the existing password in ${PG_ENV}"
  # shellcheck disable=SC1090
  PG_PASSWORD="$(grep '^POSTGRES_PASSWORD=' "${PG_ENV}" | cut -d= -f2-)"
  [ -n "${PG_PASSWORD}" ] || die "${PG_ENV} exists but carries no POSTGRES_PASSWORD"
else
  PG_PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  umask 077
  cat > "${PG_ENV}" <<ENV
POSTGRES_USER=keeper
POSTGRES_PASSWORD=${PG_PASSWORD}
POSTGRES_DB=keeper
ENV
  say "generated a password in ${PG_ENV}"
fi
chmod 600 "${PG_ENV}"

# The application's own password, which is not the owner's.
#
# Two roles and two passwords, because the whole point of the second role is
# that holding the application's credential does not let you rewrite history.
# One password shared between them would hand the owner's privileges to
# anything that read the keeper's environment file, and the separation would
# be a label rather than a boundary.
#
# The baseline migration creates keeper_app with a password equal to its own
# name, which is right for a local container reachable from nowhere and wrong
# for a host. This rotates it on every install, so the published default is
# never what a deployment runs with.
if [ -f "${APP_PG_ENV}" ]; then
  say "reusing the existing application password in ${APP_PG_ENV}"
  APP_PG_PASSWORD="$(grep '^KEEPER_APP_PASSWORD=' "${APP_PG_ENV}" | cut -d= -f2-)"
  [ -n "${APP_PG_PASSWORD}" ] || die "${APP_PG_ENV} exists but carries no KEEPER_APP_PASSWORD"
else
  APP_PG_PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  umask 077
  cat > "${APP_PG_ENV}" <<ENV
KEEPER_APP_PASSWORD=${APP_PG_PASSWORD}
ENV
  say "generated an application password in ${APP_PG_ENV}"
fi
chmod 600 "${APP_PG_ENV}"

# What the API connects as, and it is deliberately not the owner.
#
# keeper_app holds SELECT and INSERT on events and is revoked UPDATE, DELETE
# and TRUNCATE, so the running server cannot rewrite the record even if its
# own code tried to. That is the difference between append-only as a database
# guarantee and append-only as a promise about our SQL, and it is worth a
# second role and a second password.
#
# Atlas keeps the owner below, because changing the schema is exactly what
# this role may not do.
DATABASE_URL="postgresql://keeper_app:${APP_PG_PASSWORD}@127.0.0.1:${PG_PORT}/keeper"

# Atlas gets its own spelling of the same database, and the difference is not
# cosmetic. Atlas negotiates SSL by default and fails outright against a
# server that has none, which this container does not; asyncpg makes no such
# demand and is handed the plain URL. The Makefile draws the same distinction
# for local development.
ATLAS_DB_URL="postgres://keeper:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/keeper?sslmode=disable"
echo

echo "Virtual environment"
(cd "${APP_DIR}" && uv sync --locked --no-dev)
say "ok"
echo

echo "Tokens"
# The venv's python, because signing needs pyjwt and cryptography and this
# host has no reason to carry them outside it.
"${APP_DIR}/.venv/bin/python3" "${SCRIPT_DIR}/issue_tokens.py" \
  --root "${CORA_ROOT}" --jwks-url "http://127.0.0.1:${JWKS_PORT}/jwks.json" \
  ${SUBJECTS} | sed 's/^/  /'
echo

echo "Certificate"
"${APP_DIR}/.venv/bin/python3" "${SCRIPT_DIR}/issue_tls.py" \
  --root "${CORA_ROOT}" --host "${TLS_HOST}" --also ${TLS_ALSO:-} | sed 's/^/  /'
echo

echo "Environment"
# Read as one line: systemd's EnvironmentFile has no line continuation, and
# pydantic-settings parses this field as JSON.
IDENTITY_PROVIDERS="$(tr -d '\n' < "${CORA_ROOT}/etc/identity-providers.json" | tr -s ' ')"

# Carried across the rewrite rather than dropped. This file is regenerated on
# every deploy, so a value set by hand after the last one is gone unless it is
# read back first, and this is the one setting whose absence fails open: with
# no policy configured the keeper builds AllowAllAuthorize and permits every
# authenticated caller everything. A deploy that quietly turned authorization
# off would look exactly like a deploy that worked.
#
# Passing AUTHZ_POLICY_ID to this script overrides what is on disk, and
# AUTHZ_POLICY_ID= with nothing after it is how a deployment is deliberately
# put back to permissive.
if [ -z "${AUTHZ_POLICY_ID+set}" ] && [ -f "${KEEPER_ENV}" ]; then
  AUTHZ_POLICY_ID="$(sed -n 's/^AUTHZ_POLICY_ID=//p' "${KEEPER_ENV}")"
fi
AUTHZ_POLICY_ID="${AUTHZ_POLICY_ID:-}"

umask 077
cat > "${KEEPER_ENV}" <<ENV
ENVIRONMENT=${ENVIRONMENT}
DATABASE_URL=${DATABASE_URL}
LOG_LEVEL=INFO
REQUIRE_AUTHENTICATED_PRINCIPAL=true
IDENTITY_PROVIDERS=${IDENTITY_PROVIDERS}
ENV
if [ -n "${AUTHZ_POLICY_ID}" ]; then
  echo "AUTHZ_POLICY_ID=${AUTHZ_POLICY_ID}" >> "${KEEPER_ENV}"
  say "authorization is enforced against policy ${AUTHZ_POLICY_ID}"
else
  say "no policy configured, so every authenticated caller is permitted everything"
fi
chmod 600 "${KEEPER_ENV}"
say "wrote ${KEEPER_ENV}"
echo

echo "Units"
render() {
  sed -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
      -e "s|@CORA_ROOT@|${CORA_ROOT}|g" \
      -e "s|@APP_DIR@|${APP_DIR}|g" \
      -e "s|@PG_PORT@|${PG_PORT}|g" \
      -e "s|@API_PORT@|${API_PORT}|g" \
      -e "s|@JWKS_PORT@|${JWKS_PORT}|g" \
      -e "s|@API_BIND@|${API_BIND}|g" \
      "$1" > "$2"
}
render "${SCRIPT_DIR}/cora-keeper-postgres.service.in" "${UNIT_DIR}/cora-keeper-postgres.service"
render "${SCRIPT_DIR}/cora-keeper-jwks.service.in" "${UNIT_DIR}/cora-keeper-jwks.service"
render "${SCRIPT_DIR}/cora-keeper.service.in" "${UNIT_DIR}/cora-keeper.service"

# These three were installed unprefixed once, which left them as
# unnamespaced names in a directory the facility also keeps units in. A
# host that ran that version still has them, and leaving them behind
# would mean two enabled units per service, both pinned to this host and
# both able to start: two API processes on one port, and two containers
# reaching for one data directory. So the old names are taken out here
# rather than left for somebody to notice.
for retired in keeper.service keeper-jwks.service keeper-postgres.service; do
  if [ -f "${UNIT_DIR}/${retired}" ]; then
    systemctl --user disable --now "${retired}" >/dev/null 2>&1 || true
    rm -f "${UNIT_DIR}/${retired}"
    say "retired ${retired}, now carried by cora-${retired}"
  fi
done

systemctl --user daemon-reload
say "ok"
echo

echo "Database"
# The API stops before anything touches the database, for two reasons that
# both point the same way.
#
# Postgres is about to restart under it. A keeper still running against it
# has its pool severed mid-request, so the outgoing revision spends the
# restart failing whoever is calling instead of being cleanly out of the way.
#
# The second was measured here. A migration may reset a projection bookmark
# so that a read model is rebuilt against the new code. A worker belonging to
# the revision being replaced will happily take that reset and rebuild with
# its own arms, and the bookmark then sits at the end of the log with nothing
# left to replay. A migration added a column and reset the bookmark; the
# outgoing revision rebuilt the whole table before the restart, leaving the
# new column null on every row, the old column full of values no current arm
# writes, and the rebuild already marked done. Nothing failed, which is what
# made it worth a comment: the deploy reported success and the read model was
# quietly a revision behind.
#
# Ignoring the failure covers the first install, where the unit does not
# exist yet.
systemctl --user stop cora-keeper.service 2>/dev/null || true

# enable and restart, never `enable --now`. On a re-run `--now` is a no-op
# against a service that is already up, so a changed unit or a changed
# environment file is written to disk and never reaches the process. A deploy
# script that reports success while running the previous revision is worse
# than one that fails.
systemctl --user enable cora-keeper-postgres.service
systemctl --user restart cora-keeper-postgres.service
for _ in $(seq 1 60); do
  if podman exec keeper-postgres pg_isready -U keeper -d keeper >/dev/null 2>&1; then
    say "accepting connections"
    break
  fi
  sleep 2
done
podman exec keeper-postgres pg_isready -U keeper -d keeper >/dev/null 2>&1 \
  || die "postgres did not become ready; see: podman logs keeper-postgres"
echo

echo "Migrations"
# The API has been down since the Database step above, which is where the
# reasons for stopping it are.
(cd "${ATLAS_DIR}" && DATABASE_URL="${ATLAS_DB_URL}" atlas migrate apply --env local)

# After the migrations, because the role is created by the baseline and a
# password cannot be set on a role that does not exist yet. Idempotent: every
# install sets it again, which is also how a rotated password is deployed.
podman exec -i -e PGPASSWORD="${PG_PASSWORD}" keeper-postgres \
  psql -U keeper -d keeper -v ON_ERROR_STOP=1 -q \
  -c "ALTER ROLE keeper_app WITH PASSWORD '${APP_PG_PASSWORD}'" \
  || die "could not set the application role's password"
say "application role password set"
echo

echo "JWKS"
systemctl --user enable cora-keeper-jwks.service
systemctl --user restart cora-keeper-jwks.service
sleep 2
curl -fsS --max-time 5 "http://127.0.0.1:${JWKS_PORT}/jwks.json" >/dev/null \
  || die "the JWKS is not being served; the keeper could not verify a token"
say "served on 127.0.0.1:${JWKS_PORT}"
echo

echo "API"
systemctl --user enable cora-keeper.service
systemctl --user restart cora-keeper.service
sleep 3
systemctl --user is-active --quiet cora-keeper.service \
  || die "cora-keeper.service did not stay up; see: journalctl --user -u cora-keeper.service or ${CORA_ROOT}/log/keeper.log"

# Both directions, because a check that only tries the valid case cannot
# tell an enforcing deployment from an open one. This exact mistake shipped
# an unauthenticated API here once already.
CA="${CORA_ROOT}/etc/tls/ca.crt"
base="https://${TLS_HOST}:${API_PORT}"
for _ in $(seq 1 15); do
  curl -fsS --cacert "${CA}" --max-time 5 "${base}/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS --cacert "${CA}" --max-time 5 "${base}/health" >/dev/null \
  || die "the API is not answering over TLS at ${base}"

anonymous="$(curl -sS --cacert "${CA}" -o /dev/null -w '%{http_code}' "${base}/devices")"
[ "${anonymous}" = "401" ] \
  || die "an unauthenticated request got ${anonymous}, not 401; this deployment is open"

first="$(printf '%s' "${SUBJECTS}" | awk '{print $1}')"
authenticated="$(curl -sS --cacert "${CA}" -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $(cat "${CORA_ROOT}/etc/tokens/${first}.token")" "${base}/devices")"
[ "${authenticated}" = "200" ] \
  || die "a token from ${first} got ${authenticated}, not 200"

say "running, refusing anonymous callers and accepting signed ones"
echo

echo "Done. The API is at ${base}"
echo
echo "Each beamline needs two files from ${CORA_ROOT}/etc, and no more than two:"
echo "    tokens/<beamline>.token   into the home of that beamline, mode 600"
echo "    tls/ca.crt                so it can verify this server"
