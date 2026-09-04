#!/usr/bin/env bash
set -euo pipefail
APP_BASE="/opt/sports-big-board"
CURRENT="$APP_BASE/current"
STATE_DIR="/var/lib/sports-big-board"
ENV_FILE="/etc/sports-big-board/sbb.env"
VENV="$APP_BASE/media-audit-venv"
SERVICE="sports-big-board-media-audit.service"
PROBE_URL_DEFAULT="https://jonathanjoelneptune.github.io/sports-big-board/media-audit-probe.html"

if [[ ! -f "$CURRENT/media_audit_service.py" ]]; then
  echo "[media-audit] canonical service source missing: $CURRENT/media_audit_service.py"
  exit 1
fi

echo "[media-audit] Installing canonical headless-browser runtime..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y python3-venv curl ca-certificates >/dev/null

if ! command -v google-chrome-stable >/dev/null 2>&1; then
  echo "[media-audit] Installing Google Chrome stable..."
  CHROME_DEB="/tmp/google-chrome-stable_current_amd64.deb"
  curl -fsSL --retry 3 --connect-timeout 10 -o "$CHROME_DEB" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y "$CHROME_DEB" >/dev/null
  rm -f "$CHROME_DEB"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --disable-pip-version-check --quiet 'selenium==4.27.1'

mkdir -p "$STATE_DIR/media-audit" "$STATE_DIR/.cache"
chown -R sportsbigboard:sportsbigboard "$STATE_DIR/media-audit" "$STATE_DIR/.cache"

if [[ -f "$ENV_FILE" ]]; then
  if ! grep -q '^SBB_MEDIA_AUDIT_PROBE_URL=' "$ENV_FILE"; then
    echo "SBB_MEDIA_AUDIT_PROBE_URL=$PROBE_URL_DEFAULT" >> "$ENV_FILE"
  fi
  if ! grep -q '^SBB_MEDIA_AUDIT_PORT=' "$ENV_FILE"; then
    echo "SBB_MEDIA_AUDIT_PORT=8091" >> "$ENV_FILE"
  fi
  if ! grep -q '^SBB_MEDIA_AUDIT_TIMEZONE=' "$ENV_FILE"; then
    echo "SBB_MEDIA_AUDIT_TIMEZONE=America/Los_Angeles" >> "$ENV_FILE"
  fi
fi

cat > "/etc/systemd/system/$SERVICE" <<'UNIT'
[Unit]
Description=Sports Big Board canonical Media Health Audit worker
After=network-online.target sports-big-board.service
Wants=network-online.target
RequiresMountsFor=/var/lib/sports-big-board

[Service]
Type=simple
User=sportsbigboard
Group=sportsbigboard
WorkingDirectory=/opt/sports-big-board/current
EnvironmentFile=/etc/sports-big-board/sbb.env
Environment=HOME=/var/lib/sports-big-board
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/sports-big-board/media-audit-venv/bin/python /opt/sports-big-board/current/media_audit_service.py
Restart=always
RestartSec=5
TimeoutStopSec=40
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

# Add a dedicated Caddy route. handle_path strips /api/media-audit before proxying.
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/caddy/Caddyfile')
text=p.read_text(encoding='utf-8')
marker='    handle_path /api/media-audit/* {\n        reverse_proxy 127.0.0.1:8091\n    }\n'
if marker not in text:
    needle='    reverse_proxy 127.0.0.1:8080\n'
    if needle not in text:
        raise SystemExit('Sports Big Board Caddy reverse_proxy line not found')
    text=text.replace(needle,marker+needle,1)
    p.write_text(text,encoding='utf-8')
PY

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1 || true
systemctl restart "$SERVICE"
caddy validate --config /etc/caddy/Caddyfile >/dev/null
systemctl restart caddy

# Pre-warm Selenium Manager/ChromeDriver against a local data page. The production
# probe page is published after the backend job, so this check intentionally does
# not depend on GitHub Pages already serving the new probe generation.
echo "[media-audit] Validating controlled Chromium startup..."
runuser -u sportsbigboard -- env HOME="$STATE_DIR" "$VENV/bin/python" - <<'PY'
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
o=Options()
for a in ('--headless=new','--no-sandbox','--disable-dev-shm-usage','--mute-audio','--autoplay-policy=no-user-gesture-required'):
    o.add_argument(a)
d=webdriver.Chrome(options=o)
d.set_page_load_timeout(20)
d.get('data:text/html,<title>SBB canonical audit ready</title><p>ready</p>')
print('Chrome',d.capabilities.get('browserVersion','?'),'ready')
d.quit()
PY

for attempt in {1..30}; do
  if curl -fsS --max-time 5 http://127.0.0.1:8091/status > /tmp/sbb-media-audit-health.json; then
    echo "[media-audit] canonical audit service is healthy"
    cat /tmp/sbb-media-audit-health.json
    exit 0
  fi
  if ! systemctl is-active --quiet "$SERVICE"; then
    journalctl -u "$SERVICE" --no-pager -n 80 || true
    exit 1
  fi
  sleep 2
done

echo "[media-audit] service failed health check"
journalctl -u "$SERVICE" --no-pager -n 100 || true
exit 1
