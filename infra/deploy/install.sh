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
API_PORT="${API_PORT:-8000}"

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
umask 077
cat > "${KEEPER_ENV}" <<ENV
APP_ENV=${APP_ENV}
DATABASE_URL=${DATABASE_URL}
LOG_LEVEL=INFO
ENV
chmod 600 "${KEEPER_ENV}"
say "wrote ${KEEPER_ENV}"
echo

echo "Virtual environment"
(cd "${APP_DIR}" && uv sync --locked --no-dev)
say "ok"
echo

echo "Units"
render() {
  sed -e "s|@DEPLOY_HOST@|${DEPLOY_HOST}|g" \
      -e "s|@CORA_ROOT@|${CORA_ROOT}|g" \
      -e "s|@APP_DIR@|${APP_DIR}|g" \
      -e "s|@PG_PORT@|${PG_PORT}|g" \
      -e "s|@API_PORT@|${API_PORT}|g" \
      "$1" > "$2"
}
render "${SCRIPT_DIR}/keeper-postgres.service.in" "${UNIT_DIR}/keeper-postgres.service"
render "${SCRIPT_DIR}/keeper.service.in" "${UNIT_DIR}/keeper.service"
systemctl --user daemon-reload
say "ok"
echo

echo "Database"
systemctl --user enable --now keeper-postgres.service
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
(cd "${ATLAS_DIR}" && DATABASE_URL="${ATLAS_DB_URL}" atlas migrate apply --env local)
echo

echo "API"
systemctl --user enable --now keeper.service
sleep 3
systemctl --user is-active --quiet keeper.service \
  || die "keeper.service did not stay up; see: journalctl --user -u keeper.service or ${CORA_ROOT}/log/keeper.log"
say "running"
echo

echo "Done. The API is on 127.0.0.1:${API_PORT} and reachable from your machine with:"
echo "    ssh -N -L ${API_PORT}:127.0.0.1:${API_PORT} ${DEPLOY_HOST}"
