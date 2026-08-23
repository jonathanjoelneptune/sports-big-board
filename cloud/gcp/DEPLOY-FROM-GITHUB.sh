#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
PROJECT_ID="${SBB_PROJECT_ID:-}"
ZONE="${SBB_ZONE:-us-west2-b}"
VM_NAME="${SBB_VM_NAME:-sports-big-board}"
COMMIT_SHA="${GITHUB_SHA:-manual}"
SHORT_SHA="${COMMIT_SHA:0:12}"
if [[ -z "$VERSION" ]]; then echo "VERSION file is empty."; exit 1; fi
if [[ -z "$PROJECT_ID" ]]; then echo "SBB_PROJECT_ID is required."; exit 1; fi
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ARCHIVE="$TMP/sbb-release.tgz"
tar --exclude='.git' --exclude='.pages-dist' --exclude='gha-creds-*.json' \
  --exclude='*.sqlite3' --exclude='*.sqlite3-wal' --exclude='*.sqlite3-shm' \
  -czf "$ARCHIVE" -C "$ROOT" .
REMOTE_ARCHIVE="/tmp/sbb-release-${SHORT_SHA}.tgz"
echo "Deploying Sports Big Board v${VERSION} (${SHORT_SHA}) to ${VM_NAME} in ${ZONE}..."
gcloud compute scp "$ARCHIVE" "$VM_NAME:$REMOTE_ARCHIVE" \
  --zone "$ZONE" --project "$PROJECT_ID" --quiet --ssh-key-expire-after=10m
gcloud compute ssh "$VM_NAME" \
  --zone "$ZONE" --project "$PROJECT_ID" --quiet --ssh-key-expire-after=10m \
  --command="sudo env SBB_RELEASE_VERSION='$VERSION' SBB_RELEASE_SHA='$SHORT_SHA' SBB_REMOTE_ARCHIVE='$REMOTE_ARCHIVE' bash -s" <<'REMOTE'
set -euo pipefail
VERSION="${SBB_RELEASE_VERSION:?}"
SHA="${SBB_RELEASE_SHA:?}"
ARCHIVE="${SBB_REMOTE_ARCHIVE:?}"
APP_BASE="/opt/sports-big-board"
RELEASE_DIR="$APP_BASE/releases/v${VERSION}-${SHA}"
CURRENT_LINK="$APP_BASE/current"
PREVIOUS="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
rollback(){
  echo "[deploy] New backend failed health checks. Rolling back..."
  if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
    ln -sfn "$PREVIOUS" "$CURRENT_LINK"
    systemctl restart sports-big-board || true
  fi
  rm -rf "$RELEASE_DIR"
  rm -f "$ARCHIVE"
}
trap rollback ERR
rm -rf "$RELEASE_DIR"; mkdir -p "$RELEASE_DIR"
tar -xzf "$ARCHIVE" -C "$RELEASE_DIR"
chown -R root:root "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
systemctl restart sports-big-board
healthy=0
for attempt in {1..24}; do
  if curl -fsS --max-time 5 http://127.0.0.1:8080/api/status > /tmp/sbb-health.json; then healthy=1; break; fi
  sleep 2
done
if [[ "$healthy" != "1" ]]; then
  echo "[deploy] Local backend health check failed."
  journalctl -u sports-big-board --no-pager -n 80 || true
  false
fi
LOCAL_VERSION="$(python3 -c 'import json; print(json.load(open("/tmp/sbb-health.json")).get("version", ""))' 2>/dev/null || true)"
if [[ "$LOCAL_VERSION" != "$VERSION" ]]; then
  echo "[deploy] Version mismatch: expected backend v${VERSION}, got v${LOCAL_VERSION:-UNKNOWN}."
  journalctl -u sports-big-board --no-pager -n 80 || true
  false
fi

# Validate the public Caddy/TLS route from the VM too. A failure here rolls the
# symlink back before GitHub Pages can publish a frontend that points at a bad API.
PUBLIC_HOST="$(awk '/^[A-Za-z0-9.-]+[[:space:]]*\{/{print $1; exit}' /etc/caddy/Caddyfile 2>/dev/null || true)"
if [[ -n "$PUBLIC_HOST" ]]; then
  public_healthy=0
  for attempt in {1..12}; do
    if curl -fsS --max-time 8 "https://${PUBLIC_HOST}/api/status" > /tmp/sbb-public-health.json; then public_healthy=1; break; fi
    sleep 3
  done
  if [[ "$public_healthy" != "1" ]]; then
    echo "[deploy] Public HTTPS backend health check failed for $PUBLIC_HOST."
    journalctl -u caddy -u sports-big-board --no-pager -n 80 || true
    false
  fi
  PUBLIC_VERSION="$(python3 -c 'import json; print(json.load(open("/tmp/sbb-public-health.json")).get("version", ""))' 2>/dev/null || true)"
  if [[ "$PUBLIC_VERSION" != "$VERSION" ]]; then
    echo "[deploy] Public backend version mismatch: expected v${VERSION}, got v${PUBLIC_VERSION:-UNKNOWN}."
    false
  fi
fi
trap - ERR
rm -f "$ARCHIVE"
echo "[deploy] Backend v${VERSION}-${SHA} is healthy."
cat /tmp/sbb-health.json
CURRENT_REAL="$(readlink -f "$CURRENT_LINK")"
mapfile -t RELEASES < <(find "$APP_BASE/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
count=0
for release in "${RELEASES[@]}"; do
  count=$((count+1))
  if (( count <= 6 )); then continue; fi
  [[ "$release" == "$CURRENT_REAL" ]] && continue
  rm -rf "$release"
done
REMOTE
