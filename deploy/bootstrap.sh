#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — provision a fresh Ubuntu 22.04/24.04 droplet for the
#                MMR FastAPI sidecar at api.mymetalroofer.net
# =============================================================================
# Idempotent: safe to re-run. Skips work that's already done.
#
# Usage (run as root on a fresh droplet):
#   curl -fsSL https://raw.githubusercontent.com/CrimsonCVoid/Mymetalrooferbackupmvp/<branch>/deploy/bootstrap.sh | bash
# Or, if you scp'd the deploy/ folder up:
#   sudo bash /root/deploy/bootstrap.sh
#
# What this does:
#   1. apt update + installs (python3.11, git, caddy, build deps for rasterio/opencv)
#   2. Creates `mmr` system user with home /opt/mmr-api
#   3. Clones repo to /opt/mmr-api/app  (or pulls if already there)
#   4. Builds Python venv + installs requirements.txt
#   5. Drops Caddyfile into /etc/caddy/Caddyfile
#   6. Drops systemd unit at /etc/systemd/system/mmr-api.service
#   7. Opens UFW for 80/443 + 22, blocks 8000 (sidecar listens on loopback only)
#   8. Reminds operator to fill /opt/mmr-api/app/.env before `systemctl start`
# =============================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/CrimsonCVoid/Mymetalrooferbackupmvp.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_USER="mmr"
APP_HOME="/opt/mmr-api"
APP_DIR="$APP_HOME/app"
DEPLOY_DIR="$APP_DIR/deploy"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[fatal]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root (sudo bash $0)"

# -----------------------------------------------------------------------------
# 1. System packages
# -----------------------------------------------------------------------------
log "Updating apt + installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y

# Pick the right Python: prefer 3.12 (Ubuntu 24.04 stock), fall back to
# 3.11 (Ubuntu 22.04 stock). Both work for roof_pipeline (requires 3.11+).
if apt-cache show python3.12 >/dev/null 2>&1; then
    PY_PKG="python3.12"
elif apt-cache show python3.11 >/dev/null 2>&1; then
    PY_PKG="python3.11"
else
    die "Neither python3.12 nor python3.11 is available in apt. Add deadsnakes PPA."
fi
log "Using $PY_PKG (Ubuntu $(. /etc/os-release && echo $VERSION_ID))"

apt-get install -y --no-install-recommends \
    "$PY_PKG" "${PY_PKG}-venv" "${PY_PKG}-dev" \
    build-essential pkg-config \
    git curl ca-certificates gnupg \
    libgdal-dev gdal-bin \
    libgl1 libglib2.0-0 \
    ufw

# Caddy (official APT repo)
if ! command -v caddy >/dev/null 2>&1; then
    log "Installing Caddy from official APT repo"
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -y
    apt-get install -y caddy
fi

# -----------------------------------------------------------------------------
# 2. Application user + directories
# -----------------------------------------------------------------------------
if ! id "$APP_USER" >/dev/null 2>&1; then
    log "Creating system user '$APP_USER'"
    useradd --system --create-home --home-dir "$APP_HOME" --shell /bin/bash "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_HOME"

# -----------------------------------------------------------------------------
# 3. Repo
# -----------------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
    log "Repo already present — pulling $REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" checkout --quiet "$REPO_BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard "origin/$REPO_BRANCH"
else
    log "Cloning $REPO_URL ($REPO_BRANCH) into $APP_DIR"
    sudo -u "$APP_USER" git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$APP_DIR"
fi

# -----------------------------------------------------------------------------
# 4. Python venv + dependencies
# -----------------------------------------------------------------------------
log "Building Python venv + installing requirements"
sudo -u "$APP_USER" "$PY_PKG" -m venv "$APP_HOME/venv"
sudo -u "$APP_USER" "$APP_HOME/venv/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$APP_USER" "$APP_HOME/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# -----------------------------------------------------------------------------
# 5. .env scaffold (operator must fill in real values before `systemctl start`)
# -----------------------------------------------------------------------------
ENV_FILE="$APP_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    log "Writing $ENV_FILE template (you MUST fill it in before starting the service)"
    cat > "$ENV_FILE" <<'EOF'
# Filled in by operator. Never commit this file. See deploy/RUNBOOK.md.
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
GOOGLE_SOLAR_API_KEY=
INTERNAL_API_KEY=
CORS_ORIGINS=["https://www.mymetalroofer.net","https://mymetalroofer.net","https://*.vercel.app"]
STORAGE_BUCKET=pipeline-outputs
TRAINING_BUCKET=training-data
PDF_OUTPUT_BUCKET=pdf-outputs
PDF_SIGNED_URL_TTL_SECONDS=3600
DEV_ALLOW_UNAUTH=false
EOF
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 0600 "$ENV_FILE"
else
    log ".env already exists — leaving it alone"
fi

# -----------------------------------------------------------------------------
# 6. Caddy + systemd
# -----------------------------------------------------------------------------
log "Installing Caddyfile + mmr-api.service"
install -m 0644 "$DEPLOY_DIR/Caddyfile" /etc/caddy/Caddyfile
install -m 0644 "$DEPLOY_DIR/mmr-api.service" /etc/systemd/system/mmr-api.service
systemctl daemon-reload
systemctl enable caddy mmr-api

# -----------------------------------------------------------------------------
# 7. Firewall
# -----------------------------------------------------------------------------
log "Configuring UFW"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'ssh'
ufw allow 80/tcp comment 'caddy http (acme)'
ufw allow 443/tcp comment 'caddy https'
ufw --force enable

# -----------------------------------------------------------------------------
# 8. Done — operator handoff
# -----------------------------------------------------------------------------
cat <<EOF

\033[1;32m==> Bootstrap complete.\033[0m

Next steps (do these in order):

  1. Add a Porkbun A-record:
       Type:  A
       Host:  api
       Value: \$(curl -s4 https://ifconfig.me)
       TTL:   600

  2. Wait ~2 min for DNS, then verify:
       dig +short api.mymetalroofer.net

  3. Edit /opt/mmr-api/app/.env and fill in the secrets
     (see ROTATE_THESE.md for what to rotate first):
       sudo -u mmr nano /opt/mmr-api/app/.env

  4. Start the services:
       sudo systemctl restart caddy mmr-api
       sudo systemctl status mmr-api --no-pager
       sudo journalctl -u mmr-api -n 50 --no-pager

  5. Smoke test from your laptop:
       curl -i https://api.mymetalroofer.net/health
       (Caddy will provision a Let's Encrypt cert on first request.)

EOF
