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

ensure_env_var() {
  local name="$1"
  local value="$2"
  if ! grep -q "^${name}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$name" "$value" >> "$ENV_FILE"
  fi
}

read_env_var() {
  local name="$1"
  sed -n "s/^${name}=//p" "$ENV_FILE" | head -n1
}

ensure_saas_env() {
  local pg_password session_secret database_url
  pg_password="$(read_env_var OPENSMS_POSTGRES_PASSWORD)"
  if [[ -z "$pg_password" ]]; then
    pg_password="$(openssl rand -hex 32)"
    ensure_env_var OPENSMS_POSTGRES_PASSWORD "$pg_password"
  fi

  session_secret="$(read_env_var OPENSMS_SAAS_SESSION_SECRET)"
  if [[ -z "$session_secret" ]]; then
    session_secret="$(openssl rand -hex 32)"
    ensure_env_var OPENSMS_SAAS_SESSION_SECRET "$session_secret"
  fi

  database_url="postgresql+psycopg://opensms:${pg_password}@opensms-postgres:5432/opensms"
  ensure_env_var OPENSMS_SAAS_DATABASE_URL "$database_url"
  ensure_env_var OPENSMS_SAAS_ENABLED "1"
  ensure_env_var OPENSMS_SAAS_SECURE_COOKIES "0"
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
chown -R 10001:10001 "$DATA_DIR"
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

ensure_saas_env
chmod 600 "$ENV_FILE"

log "Installing rcs management command"
cat > /usr/local/bin/rcs <<'RCSCLI'
#!/usr/bin/env bash
set -Eeuo pipefail
INSTALL_DIR="/opt/opensms-rcs"
GATEWAY_DIR="$INSTALL_DIR/gateway"
ENV_FILE="$GATEWAY_DIR/.env"
DATA_DIR="$GATEWAY_DIR/data"
BRANCH="feature/remote-connector-v1"
HEALTH_URL="http://127.0.0.1:8080/healthz"
READY_URL="http://127.0.0.1:8080/readyz"

require_install() {
  [[ -d "$INSTALL_DIR/.git" ]] || { echo "OpenSMS/RCS is not installed in $INSTALL_DIR" >&2; exit 1; }
}

ensure_env_var() {
  local name="$1"
  local value="$2"
  if ! grep -q "^${name}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$name" "$value" >> "$ENV_FILE"
  fi
}

read_env_var() {
  local name="$1"
  sed -n "s/^${name}=//p" "$ENV_FILE" | head -n1
}

ensure_saas_env() {
  local pg_password session_secret
  pg_password="$(read_env_var OPENSMS_POSTGRES_PASSWORD)"
  if [[ -z "$pg_password" ]]; then
    pg_password="$(openssl rand -hex 32)"
    ensure_env_var OPENSMS_POSTGRES_PASSWORD "$pg_password"
  fi
  session_secret="$(read_env_var OPENSMS_SAAS_SESSION_SECRET)"
  if [[ -z "$session_secret" ]]; then
    session_secret="$(openssl rand -hex 32)"
    ensure_env_var OPENSMS_SAAS_SESSION_SECRET "$session_secret"
  fi
  ensure_env_var OPENSMS_SAAS_DATABASE_URL "postgresql+psycopg://opensms:${pg_password}@opensms-postgres:5432/opensms"
  ensure_env_var OPENSMS_SAAS_ENABLED "1"
  ensure_env_var OPENSMS_SAAS_SECURE_COOKIES "0"
  chmod 600 "$ENV_FILE"
}

wait_health() {
  for _ in $(seq 1 45); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && curl -fsS "$READY_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

show_status() {
  require_install
  cd "$GATEWAY_DIR"
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$LAN_IP" ]] || LAN_IP="127.0.0.1"
  echo "RCS_BRANCH=$(git -C "$INSTALL_DIR" branch --show-current)"
  echo "RCS_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short=12 HEAD)"
  echo "DOCKER_STATUS=$(systemctl is-active docker || true)"
  echo "GATEWAY_CONTAINER_STATUS=$(docker compose ps --status running -q opensms-gateway | grep -q . && echo running || echo stopped)"
  echo "POSTGRES_CONTAINER_STATUS=$(docker compose ps --status running -q opensms-postgres | grep -q . && echo running || echo stopped)"
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then echo "HEALTHZ=PASS"; else echo "HEALTHZ=FAIL"; fi
  if curl -fsS "$READY_URL" >/dev/null 2>&1; then echo "READYZ=PASS"; else echo "READYZ=FAIL"; fi
  echo "SAAS_STATUS=ENABLED"
  echo "SAAS_DATABASE=POSTGRESQL"
  echo "LOCAL_ACCESS=http://${LAN_IP}:8080"
}

case "${1:-status}" in
  update)
    require_install
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" merge --ff-only "origin/$BRANCH"
    ensure_saas_env
    chown -R 10001:10001 "$DATA_DIR"
    chmod 700 "$DATA_DIR"
    cd "$GATEWAY_DIR"
    docker compose up -d --build
    wait_health || { docker compose ps; docker compose logs --tail=120; exit 1; }
    show_status
    ;;
  status)
    show_status
    ;;
  restart)
    require_install
    cd "$GATEWAY_DIR"
    docker compose restart
    wait_health || { docker compose ps; docker compose logs --tail=120; exit 1; }
    show_status
    ;;
  logs)
    require_install
    cd "$GATEWAY_DIR"
    docker compose logs --tail=200 -f
    ;;
  *)
    echo "Usage: rcs {update|status|restart|logs}" >&2
    exit 2
    ;;
esac
RCSCLI
chmod 755 /usr/local/bin/rcs

cd "$GATEWAY_DIR"
log "Building and starting gateway and SaaS database"
docker compose up -d --build

log "Waiting for health checks"
health_ok=0
for _ in $(seq 1 45); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && curl -fsS "$READY_URL" >/dev/null 2>&1; then
    health_ok=1
    break
  fi
  sleep 2
done

if [[ "$health_ok" -ne 1 ]]; then
  docker compose ps >&2 || true
  docker compose logs --tail=120 >&2 || true
  fail "gateway did not become healthy"
fi

RCS_BRANCH="$(git -C "$INSTALL_DIR" branch --show-current)"
RCS_COMMIT="$(git -C "$INSTALL_DIR" rev-parse --short=12 HEAD)"
DOCKER_STATUS="$(systemctl is-active docker)"
CONTAINER_ID="$(docker compose ps -q opensms-gateway)"
POSTGRES_ID="$(docker compose ps -q opensms-postgres)"
[[ -n "$CONTAINER_ID" ]] || fail "gateway container id not found after health validation"
[[ -n "$POSTGRES_ID" ]] || fail "postgres container id not found after health validation"
GATEWAY_CONTAINER_STATUS="$(docker inspect -f '{{.State.Status}}' "$CONTAINER_ID")"
POSTGRES_CONTAINER_STATUS="$(docker inspect -f '{{.State.Status}}' "$POSTGRES_ID")"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$LAN_IP" ]] || LAN_IP="127.0.0.1"

printf '\n'
printf '%s\n' '================ OpenSMS/RCS FINAL STATUS ================'
printf 'RCS_BRANCH=%s\n' "$RCS_BRANCH"
printf 'RCS_COMMIT=%s\n' "$RCS_COMMIT"
printf 'DOCKER_STATUS=%s\n' "$DOCKER_STATUS"
printf 'GATEWAY_CONTAINER_STATUS=%s\n' "$GATEWAY_CONTAINER_STATUS"
printf 'POSTGRES_CONTAINER_STATUS=%s\n' "$POSTGRES_CONTAINER_STATUS"
printf 'HEALTHZ=PASS\n'
printf 'READYZ=PASS\n'
printf 'SAAS_STATUS=ENABLED\n'
printf 'SAAS_DATABASE=POSTGRESQL\n'
printf 'RCS_IP=%s\n' "$LAN_IP"
printf 'RCS_PORT=8080\n'
printf 'LOCAL_ACCESS=http://%s:8080\n' "$LAN_IP"
printf 'INSTALL_DIR=%s\n' "$INSTALL_DIR"
printf 'CREDENTIALS_FILE=%s\n' "$ENV_FILE"
printf 'TOKENS_PRINTED=NO\n'
printf 'MANAGEMENT_COMMAND=rcs\n'
printf 'FINAL_STATUS=PASS\n'
printf '%s\n' '=========================================================='
