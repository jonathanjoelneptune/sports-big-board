#!/usr/bin/env bash
set -euo pipefail
PUBLIC_HOST="${1:?public hostname required}"
DATA_DISK="${2:-sports-big-board-data}"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$SOURCE_ROOT/VERSION")"
DEVICE="/dev/disk/by-id/google-${DATA_DISK}"
STATE_DIR="/var/lib/sports-big-board"
APP_BASE="/opt/sports-big-board"
RELEASE_DIR="$APP_BASE/releases/v${VERSION}"
ENV_DIR="/etc/sports-big-board"
ENV_FILE="$ENV_DIR/sbb.env"

echo "[vm] Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
# v4.5.5 Media Intelligence uses ffmpeg for bounded audio sampling and the latest
# stable yt-dlp plus Deno for current YouTube JavaScript challenge/format support.
apt-get install -y python3 sqlite3 curl caddy ffmpeg unzip ca-certificates >/dev/null
MEDIA_TOOL_TMP="$(mktemp -d)"
case "$(uname -m)" in
  x86_64|amd64) DENO_TARGET="x86_64-unknown-linux-gnu" ;;
  aarch64|arm64) DENO_TARGET="aarch64-unknown-linux-gnu" ;;
  *) echo "Unsupported architecture for Deno: $(uname -m)"; exit 1 ;;
esac
curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 \
  -o "$MEDIA_TOOL_TMP/yt-dlp" \
  https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp
install -m 0755 "$MEDIA_TOOL_TMP/yt-dlp" /usr/local/bin/yt-dlp
curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 180 \
  -o "$MEDIA_TOOL_TMP/deno.zip" \
  "https://github.com/denoland/deno/releases/latest/download/deno-${DENO_TARGET}.zip"
unzip -q -o "$MEDIA_TOOL_TMP/deno.zip" -d "$MEDIA_TOOL_TMP/deno"
install -m 0755 "$MEDIA_TOOL_TMP/deno/deno" /usr/local/bin/deno
rm -rf "$MEDIA_TOOL_TMP"
hash -r
echo "[vm] yt-dlp $(yt-dlp --version) • $(deno --version | head -n 1)"

echo "[vm] Mounting persistent Sports Big Board state disk..."
mkdir -p "$STATE_DIR"
if [[ ! -e "$DEVICE" ]]; then echo "Persistent disk device not found: $DEVICE"; exit 1; fi
if ! blkid "$DEVICE" >/dev/null 2>&1; then mkfs.ext4 -F "$DEVICE" >/dev/null; fi
UUID="$(blkid -s UUID -o value "$DEVICE")"
if ! grep -q "UUID=$UUID" /etc/fstab; then echo "UUID=$UUID $STATE_DIR ext4 defaults,nofail 0 2" >> /etc/fstab; fi
mountpoint -q "$STATE_DIR" || mount "$STATE_DIR"

if ! id sportsbigboard >/dev/null 2>&1; then useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin sportsbigboard; fi
chown -R sportsbigboard:sportsbigboard "$STATE_DIR"
chmod 750 "$STATE_DIR"
mkdir -p "$STATE_DIR/cache" "$STATE_DIR/backups"
chown -R sportsbigboard:sportsbigboard "$STATE_DIR/cache" "$STATE_DIR/backups"

mkdir -p "$APP_BASE/releases" "$ENV_DIR"
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
cp -a "$SOURCE_ROOT"/. "$RELEASE_DIR"/
chown -R root:root "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$APP_BASE/current"

# Secrets were uploaded separately so they never become part of the release archive or Pages artifact.
install -m 600 -o root -g root /tmp/sbb-secrets.env "$ENV_FILE"
cat >> "$ENV_FILE" <<ENV
PORT=8080
SBB_BIND_HOST=127.0.0.1
SBB_CLOUD_MODE=1
SBB_STATE_DIR=$STATE_DIR
SBB_ALLOWED_ORIGINS=https://$PUBLIC_HOST
SBB_ALLOWED_ORIGIN_SUFFIXES=.github.io
SBB_HISTORY_BACKFILL_DAYS=400
SBB_HISTORY_BACKFILL_MEDIA=1
SBB_MEDIA_CACHE_MAX_BYTES=1073741824
SBB_MEDIA_CACHE_TTL=86400
PYTHONUNBUFFERED=1
ENV

cat > /etc/systemd/system/sports-big-board.service <<'UNIT'
[Unit]
Description=Sports Big Board always-on backend
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/var/lib/sports-big-board

[Service]
Type=simple
User=sportsbigboard
Group=sportsbigboard
WorkingDirectory=/opt/sports-big-board/current
EnvironmentFile=/etc/sports-big-board/sbb.env
ExecStart=/usr/bin/python3 /opt/sports-big-board/current/server.py
Restart=always
RestartSec=3
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/sports-big-board-backup.service <<'UNIT'
[Unit]
Description=Back up Sports Big Board SQLite state
After=sports-big-board.service

[Service]
Type=oneshot
User=sportsbigboard
Group=sportsbigboard
EnvironmentFile=/etc/sports-big-board/sbb.env
ExecStart=/usr/bin/python3 /opt/sports-big-board/current/cloud/vm/backup_state.py
UNIT

cat > /etc/systemd/system/sports-big-board-backup.timer <<'UNIT'
[Unit]
Description=Daily Sports Big Board state backup

[Timer]
OnCalendar=*-*-* 05:20:00
Persistent=true
RandomizedDelaySec=900

[Install]
WantedBy=timers.target
UNIT

cat > /etc/caddy/Caddyfile <<CADDY
$PUBLIC_HOST {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8080
    header {
        -Server
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}
CADDY

systemctl daemon-reload

# Structural v4 preflight runs before service start. Legacy/structurally invalid
# catalogs are reconstructed offline; healthy normalized v4 catalogs are kept in
# place and relationship upgrades are repaired by the backend without resetting
# discovery/backfill progress.
runuser -u sportsbigboard -- env SBB_STATE_DIR="$STATE_DIR" \
  /usr/bin/python3 "$APP_BASE/current/tools/ensure_history_v4.py" --state-dir "$STATE_DIR"

systemctl enable --now sports-big-board.service
systemctl enable --now sports-big-board-backup.timer
caddy validate --config /etc/caddy/Caddyfile >/dev/null
systemctl enable caddy >/dev/null 2>&1 || true
systemctl restart caddy

# Let Caddy obtain the first certificate and then prove the app is reachable.
for i in {1..24}; do
  if curl -fsS --max-time 5 "https://$PUBLIC_HOST/api/status" >/dev/null 2>&1; then
    echo "[vm] HTTPS health check passed: https://$PUBLIC_HOST/api/status"
    exit 0
  fi
  sleep 5
done

echo "[vm] Services installed, but the public HTTPS health check has not succeeded yet."
echo "[vm] Check: journalctl -u caddy -u sports-big-board --no-pager -n 100"
exit 1
