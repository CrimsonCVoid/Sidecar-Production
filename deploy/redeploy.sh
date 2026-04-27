#!/usr/bin/env bash
# =============================================================================
# redeploy.sh — wipe + re-clone + restart the MMR sidecar on the droplet
# =============================================================================
# Run on the droplet as root:
#   sudo bash /opt/mmr-api/app/deploy/redeploy.sh
#
# Or from your laptop (one-shot, no need to scp):
#   ssh root@<DROPLET_IP> 'bash -s' < ~/Mymetalrooferbackupmvp-firstcommit/deploy/redeploy.sh
#
# What it does:
#   1. Stops mmr-api (so we can safely nuke files in use)
#   2. Backs up .env to /root/mmr-env-backup.<timestamp> (paranoia)
#   3. Deletes /opt/mmr-api/app entirely
#   4. Re-clones the repo fresh from GitHub
#   5. Restores .env
#   6. Reinstalls Python deps (requirements may have changed)
#   7. Reinstalls Caddyfile + systemd unit (in case those changed in the repo)
#   8. Starts mmr-api and tails logs until /health returns 200
#
# What it preserves:
#   - /opt/mmr-api/app/.env  (your secrets)
#   - /var/log/caddy/        (access logs)
#   - The mmr user
#
# What it destroys:
#   - Everything else under /opt/mmr-api/app, including any local edits.
#     Untracked output/ files, scratch notebooks, anything not in git: GONE.
# =============================================================================

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/CrimsonCVoid/Mymetalrooferbackupmvp.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_USER="mmr"
APP_HOME="/opt/mmr-api"
APP_DIR="$APP_HOME/app"
ENV_FILE="$APP_DIR/.env"
BACKUP_DIR="/root/mmr-env-backups"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[fatal]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root (sudo bash $0)"

# -----------------------------------------------------------------------------
# 1. Stop the service (idempotent — won't fail if not running)
# -----------------------------------------------------------------------------
log "Stopping mmr-api"
systemctl stop mmr-api 2>/dev/null || warn "mmr-api was not running"

# -----------------------------------------------------------------------------
# 2. Back up .env
# -----------------------------------------------------------------------------
mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"
ENV_BACKUP=""
if [[ -f "$ENV_FILE" ]]; then
    ENV_BACKUP="$BACKUP_DIR/.env.$(date +%Y%m%d-%H%M%S)"
    cp -p "$ENV_FILE" "$ENV_BACKUP"
    log "Backed up .env → $ENV_BACKUP"
else
    warn "No existing .env found at $ENV_FILE — you'll need to fill one in after redeploy"
fi

# -----------------------------------------------------------------------------
# 3. Nuke the app dir
# -----------------------------------------------------------------------------
log "Wiping $APP_DIR"
rm -rf "$APP_DIR"

# -----------------------------------------------------------------------------
# 4. Re-clone fresh
# -----------------------------------------------------------------------------
log "Cloning $REPO_URL ($REPO_BRANCH)"
sudo -u "$APP_USER" git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$APP_DIR"

# Pre-create dirs that the systemd unit lists in ReadWritePaths=. Without
# these the service exits with status=226/NAMESPACE before uvicorn even
# starts. bootstrap.sh creates them on first install; redeploy wipes the
# entire app dir, so we must recreate them after the clone.
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_DIR/data" "$APP_DIR/output"

# -----------------------------------------------------------------------------
# 5. Restore .env
# -----------------------------------------------------------------------------
if [[ -n "$ENV_BACKUP" ]]; then
    log "Restoring .env from $ENV_BACKUP"
    cp -p "$ENV_BACKUP" "$ENV_FILE"
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 0600 "$ENV_FILE"
fi

# -----------------------------------------------------------------------------
# 6. Reinstall Python deps (requirements.txt may have changed)
# -----------------------------------------------------------------------------
log "Reinstalling Python deps"
sudo -u "$APP_USER" "$APP_HOME/venv/bin/pip" install --quiet --upgrade pip wheel
sudo -u "$APP_USER" "$APP_HOME/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# -----------------------------------------------------------------------------
# 7. Refresh systemd unit + Caddyfile (in case the repo updated them)
# -----------------------------------------------------------------------------
log "Refreshing /etc/systemd + /etc/caddy from repo"
install -m 0644 "$APP_DIR/deploy/mmr-api.service" /etc/systemd/system/mmr-api.service
install -m 0644 "$APP_DIR/deploy/Caddyfile"       /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl reload caddy 2>/dev/null || systemctl restart caddy

# -----------------------------------------------------------------------------
# 8. Start and verify
# -----------------------------------------------------------------------------
log "Starting mmr-api"
systemctl enable --now mmr-api

log "Waiting for /health to return 200 (max 60s)"
deadline=$((SECONDS + 60))
until curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health 2>/dev/null | grep -q 200; do
    if (( SECONDS > deadline )); then
        warn "Health check timed out. Recent logs:"
        journalctl -u mmr-api -n 50 --no-pager
        die "Sidecar did not become healthy within 60s"
    fi
    sleep 2
done

# Public-facing check — confirms Caddy is also healthy
public_status=$(curl -fsS -o /dev/null -w '%{http_code}' "https://api.mymetalroofer.net/health" 2>/dev/null || echo "FAIL")

cat <<EOF

\033[1;32m==> Redeploy complete.\033[0m

  Local sidecar:    http://127.0.0.1:8000/health → 200
  Public via Caddy: https://api.mymetalroofer.net/health → ${public_status}

  Git head:  $(sudo -u "$APP_USER" git -C "$APP_DIR" log -1 --oneline)
  Restart:   sudo systemctl restart mmr-api
  Logs:      sudo journalctl -u mmr-api -f
  Status:    sudo systemctl status mmr-api --no-pager

EOF
