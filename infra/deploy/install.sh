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
SUBJECTS="${SUBJECTS:-2-bm 7-bm 19-bm 32-id thinker}"

# Not a production-tier value, and that is the honest setting rather than a
# placeholder. A production tier refuses to boot without configured
# authentication and an authorization policy, neither of which exists yet.
# Naming the tier accurately is what keeps the loopback bind in the unit
# file correct instead of merely cautious.
APP_ENV="${APP_ENV:-pilot}"

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

DATABASE_URL="postgresql://keeper:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/keeper"

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

umask 077
cat > "${KEEPER_ENV}" <<ENV
APP_ENV=${APP_ENV}
DATABASE_URL=${DATABASE_URL}
LOG_LEVEL=INFO
REQUIRE_AUTHENTICATED_PRINCIPAL=true
IDENTITY_PROVIDERS=${IDENTITY_PROVIDERS}
ENV
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
render "${SCRIPT_DIR}/keeper-postgres.service.in" "${UNIT_DIR}/keeper-postgres.service"
render "${SCRIPT_DIR}/keeper-jwks.service.in" "${UNIT_DIR}/keeper-jwks.service"
render "${SCRIPT_DIR}/keeper.service.in" "${UNIT_DIR}/keeper.service"
systemctl --user daemon-reload
say "ok"
echo

echo "Database"
# enable and restart, never `enable --now`. On a re-run `--now` is a no-op
# against a service that is already up, so a changed unit or a changed
# environment file is written to disk and never reaches the process. A deploy
# script that reports success while running the previous revision is worse
# than one that fails.
systemctl --user enable keeper-postgres.service
systemctl --user restart keeper-postgres.service
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
# The API is stopped first, and for a specific reason rather than general
# caution. A migration may reset a projection bookmark so that a read model
# is rebuilt against the new code. A worker belonging to the revision being
# replaced will happily take that reset and rebuild with its own arms, and
# the bookmark then sits at the end of the log with nothing left to replay.
#
# Measured here. A migration added a column and reset the bookmark; the
# outgoing revision rebuilt the whole table before the restart, leaving the
# new column null on every row, the old column full of values no current arm
# writes, and the rebuild already marked done. Nothing failed, which is what
# made it worth a comment: the deploy reported success and the read model
# was quietly a revision behind.
#
# Ignoring the failure covers the first install, where the unit does not
# exist yet.
systemctl --user stop keeper.service 2>/dev/null || true
(cd "${ATLAS_DIR}" && DATABASE_URL="${ATLAS_DB_URL}" atlas migrate apply --env local)
echo

echo "JWKS"
systemctl --user enable keeper-jwks.service
systemctl --user restart keeper-jwks.service
sleep 2
curl -fsS --max-time 5 "http://127.0.0.1:${JWKS_PORT}/jwks.json" >/dev/null \
  || die "the JWKS is not being served; the keeper could not verify a token"
say "served on 127.0.0.1:${JWKS_PORT}"
echo

echo "API"
systemctl --user enable keeper.service
systemctl --user restart keeper.service
sleep 3
systemctl --user is-active --quiet keeper.service \
  || die "keeper.service did not stay up; see: journalctl --user -u keeper.service or ${CORA_ROOT}/log/keeper.log"

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
