#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="https://github.com/OpenSMSProject/RCS.git"
BRANCH="feature/remote-connector-v1"
INSTALL_DIR="/opt/opensms-rcs"
GATEWAY_DIR="$INSTALL_DIR/gateway"
ENV_FILE="$GATEWAY_DIR/.env"
DATA_DIR="$GATEWAY_DIR/data"
HEALTH_URL="http://127.0.0.1:8080/healthz"
READY_URL="http://127.0.0.1:8080/readyz"

log() {
  printf '[OpenSMS/RCS] %s\n' "$*"
}

fail() {
  printf '[OpenSMS/RCS] ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  fail "run this installer as root (use sudo)"
fi

[[ -r /etc/os-release ]] || fail "/etc/os-release not found"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || fail "Ubuntu is required"
case "${VERSION_ID:-}" in
  22.04|24.04) ;;
  *) fail "supported Ubuntu versions are 22.04 and 24.04 (found ${VERSION_ID:-unknown})" ;;
esac

export DEBIAN_FRONTEND=noninteractive
log "Installing system dependencies"
apt-get update -y
apt-get install -y ca-certificates curl git openssl docker.io docker-compose-v2

log "Enabling Docker"
systemctl enable --now docker

docker --version >/dev/null
docker compose version >/dev/null

if [[ -e "$INSTALL_DIR" && ! -d "$INSTALL_DIR/.git" ]]; then
  fail "$INSTALL_DIR exists but is not an OpenSMS/RCS Git checkout"
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  log "Cloning OpenSMS/RCS ($BRANCH)"
  git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
else
  log "Updating existing OpenSMS/RCS checkout"
  cd "$INSTALL_DIR"
  current_remote="$(git remote get-url origin 2>/dev/null || true)"
  [[ "$current_remote" == "$REPO_URL" || "$current_remote" == "https://github.com/OpenSMSProject/RCS" ]] \
    || fail "existing checkout has unexpected origin: ${current_remote:-none}"
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] \
    || fail "tracked local changes exist in $INSTALL_DIR; refusing to overwrite them"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git merge --ff-only "origin/$BRANCH"
fi

[[ -f "$GATEWAY_DIR/docker-compose.yml" ]] || fail "gateway/docker-compose.yml not found"
[[ -f "$GATEWAY_DIR/.env.example" ]] || fail "gateway/.env.example not found"

mkdir -p "$DATA_DIR"
chmod 700 "$DATA_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  log "Creating gateway credentials"
  API_TOKEN="$(openssl rand -hex 32)"
  ADMIN_TOKEN="$(openssl rand -hex 32)"
  umask 077
  cat > "$ENV_FILE" <<EOF
OPENSMS_API_TOKEN=${API_TOKEN}
OPENSMS_ADMIN_TOKEN=${ADMIN_TOKEN}
OPENSMS_DB_PATH=/app/data/opensms-gateway.sqlite3
OPENSMS_PAIRING_TTL_SECONDS=300
OPENSMS_HEARTBEAT_TIMEOUT_SECONDS=60
OPENSMS_PAIRING_RATE_LIMIT_PER_MINUTE=10
OPENSMS_MESSAGE_RATE_LIMIT_PER_MINUTE=120
EOF
else
  log "Preserving existing gateway credentials"
fi
chmod 600 "$ENV_FILE"

cd "$GATEWAY_DIR"
log "Building and starting gateway"
docker compose up -d --build

log "Waiting for health checks"
health_ok=0
for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && curl -fsS "$READY_URL" >/dev/null 2>&1; then
    health_ok=1
    break
  fi
  sleep 2
done

if [[ "$health_ok" -ne 1 ]]; then
  docker compose ps >&2 || true
  docker compose logs --tail=80 >&2 || true
  fail "gateway did not become healthy"
fi

printf '\n'
printf 'INSTALL_DIR=%s\n' "$INSTALL_DIR"
printf 'GATEWAY_URL=http://127.0.0.1:8080\n'
printf 'CREDENTIALS_FILE=%s\n' "$ENV_FILE"
printf 'TOKENS_PRINTED=NO\n'
printf 'FINAL_STATUS=PASS\n'
