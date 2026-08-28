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

# GitHub-hosted runners need a temporary SSH key installed on the VM. GCE
# metadata/guest-agent propagation can be slow, so use gcloud exactly once as
# the bootstrap authority: it installs the explicit key and proves the guest
# accepts it. After that successful probe, all transfer and remote execution
# uses normal OpenSSH with the SAME key. This prevents gcloud compute scp/ssh
# from starting a second metadata propagation cycle mid-deploy.
SSH_KEY_EXPIRE_AFTER="${SBB_SSH_KEY_EXPIRE_AFTER:-60m}"
SSH_READY_ATTEMPTS="${SBB_SSH_READY_ATTEMPTS:-4}"
SSH_READY_TIMEOUT_SECONDS="${SBB_SSH_READY_TIMEOUT_SECONDS:-120}"
SSH_READY_SLEEP_SECONDS="${SBB_SSH_READY_SLEEP_SECONDS:-15}"
SSH_CONNECT_TIMEOUT_SECONDS="${SBB_SSH_CONNECT_TIMEOUT_SECONDS:-20}"
SSH_UPLOAD_TIMEOUT_SECONDS="${SBB_SSH_UPLOAD_TIMEOUT_SECONDS:-180}"
SSH_REMOTE_TIMEOUT_SECONDS="${SBB_SSH_REMOTE_TIMEOUT_SECONDS:-3600}"
SSH_KEY_PATH="$TMP/google_compute_engine"
KNOWN_HOSTS="$TMP/known_hosts"
SSH_READY=0
SSH_USER=""
VM_IP=""

mkdir -p "$(dirname "$SSH_KEY_PATH")"
touch "$KNOWN_HOSTS"
chmod 600 "$KNOWN_HOSTS"

echo "[ssh] Preparing ONE runner SSH identity (temporary key lifetime: ${SSH_KEY_EXPIRE_AFTER})."
for ((attempt=1; attempt<=SSH_READY_ATTEMPTS; attempt++)); do
  echo "[ssh] Bootstrap readiness attempt ${attempt}/${SSH_READY_ATTEMPTS} (timeout ${SSH_READY_TIMEOUT_SECONDS}s)..."
  set +e
  SSH_OUTPUT="$(timeout --signal=TERM --kill-after=10s "${SSH_READY_TIMEOUT_SECONDS}s" \
    gcloud compute ssh "$VM_NAME" \
      --zone "$ZONE" --project "$PROJECT_ID" --quiet \
      --ssh-key-file="$SSH_KEY_PATH" \
      --ssh-key-expire-after="$SSH_KEY_EXPIRE_AFTER" \
      --command='printf "SBB_SSH_READY:%s\\n" "$(id -un)"' 2>&1)"
  SSH_RC=$?
  set -e
  printf '%s\n' "$SSH_OUTPUT"
  SSH_USER="$(printf '%s\n' "$SSH_OUTPUT" | sed -n 's/.*SBB_SSH_READY:\([A-Za-z0-9._-][A-Za-z0-9._-]*\).*/\1/p' | tail -n 1)"
  if [[ "$SSH_RC" == "0" && -n "$SSH_USER" ]]; then
    SSH_READY=1
    echo "[ssh] SSH READY as remote user ${SSH_USER}."
    break
  fi
  SSH_USER=""
  if [[ "$SSH_RC" == "124" || "$SSH_RC" == "137" ]]; then
    echo "[ssh] Bootstrap timed out while waiting for the GCE guest to accept the runner key."
  else
    echo "[ssh] Bootstrap failed with exit code ${SSH_RC}."
  fi
  if (( attempt < SSH_READY_ATTEMPTS )); then
    echo "[ssh] Waiting ${SSH_READY_SLEEP_SECONDS}s before retry..."
    sleep "$SSH_READY_SLEEP_SECONDS"
  fi
done

if [[ "$SSH_READY" != "1" ]]; then
  echo "[ssh] ERROR: VM never accepted the GitHub runner SSH key after bounded retries."
  echo "[ssh] No release archive was uploaded and the historical database was not touched."
  echo "[ssh] Instance summary follows for diagnosis:"
  gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
    --format='yaml(name,status,networkInterfaces[0].accessConfigs[0].natIP,metadata.items.key)' || true
  exit 1
fi

if [[ ! -s "$SSH_KEY_PATH" ]]; then
  echo "[ssh] ERROR: bootstrap reported success but the expected private key does not exist: $SSH_KEY_PATH"
  exit 1
fi
chmod 600 "$SSH_KEY_PATH"

VM_IP="$(gcloud compute instances describe "$VM_NAME" \
  --zone "$ZONE" --project "$PROJECT_ID" \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)' | tr -d '[:space:]')"
if [[ -z "$VM_IP" ]]; then
  echo "[ssh] ERROR: VM has no external NAT IP; direct transport cannot continue."
  exit 1
fi

echo "[ssh] Direct transport locked: ${SSH_USER}@${VM_IP} using ${SSH_KEY_PATH}."
SSH_OPTS=(
  -i "$SSH_KEY_PATH"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o "ConnectTimeout=${SSH_CONNECT_TIMEOUT_SECONDS}"
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
  -o StrictHostKeyChecking=accept-new
  -o "UserKnownHostsFile=${KNOWN_HOSTS}"
  -o LogLevel=ERROR
)

# Prove the direct OpenSSH path before uploading. No gcloud SSH/SCP calls are
# allowed below this point; the same accepted key is reused for the full deploy.
echo "[ssh] Verifying direct OpenSSH reuse of the accepted key..."
DIRECT_READY="$(timeout --signal=TERM --kill-after=10s 45s \
  ssh "${SSH_OPTS[@]}" "${SSH_USER}@${VM_IP}" 'printf SBB_DIRECT_SSH_READY')" || {
    rc=$?
    echo "[ssh] ERROR: direct OpenSSH reuse failed after gcloud bootstrap (exit ${rc})."
    echo "[ssh] No release archive was uploaded and the historical database was not touched."
    exit "$rc"
  }
if [[ "$DIRECT_READY" != *"SBB_DIRECT_SSH_READY"* ]]; then
  echo "[ssh] ERROR: direct OpenSSH probe returned an unexpected response."
  exit 1
fi
echo "[ssh] DIRECT SSH READY. No further gcloud SSH propagation will occur."

echo "[upload] Uploading release archive over the established key..."
set +e
timeout --signal=TERM --kill-after=10s "${SSH_UPLOAD_TIMEOUT_SECONDS}s" \
  scp "${SSH_OPTS[@]}" "$ARCHIVE" "${SSH_USER}@${VM_IP}:${REMOTE_ARCHIVE}"
SCP_RC=$?
set -e
if [[ "$SCP_RC" != "0" ]]; then
  echo "[upload] ERROR: release upload failed or exceeded the ${SSH_UPLOAD_TIMEOUT_SECONDS}s transfer limit (exit ${SCP_RC})."
  echo "[upload] Historical database has not been touched."
  exit "$SCP_RC"
fi
echo "[upload] RELEASE UPLOAD COMPLETE."

echo "[remote] Starting v4 deployment and catalog preflight over the established key..."
timeout --signal=TERM --kill-after=30s "${SSH_REMOTE_TIMEOUT_SECONDS}s" \
  ssh "${SSH_OPTS[@]}" "${SSH_USER}@${VM_IP}" \
  "sudo env SBB_RELEASE_VERSION='$VERSION' SBB_RELEASE_SHA='$SHORT_SHA' SBB_REMOTE_ARCHIVE='$REMOTE_ARCHIVE' bash -s" <<'REMOTE'
set -euo pipefail
VERSION="${SBB_RELEASE_VERSION:?}"
SHA="${SBB_RELEASE_SHA:?}"
ARCHIVE="${SBB_REMOTE_ARCHIVE:?}"
APP_BASE="/opt/sports-big-board"
RELEASE_DIR="$APP_BASE/releases/v${VERSION}-${SHA}"
CURRENT_LINK="$APP_BASE/current"
PREVIOUS="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
STATE_DIR="/var/lib/sports-big-board"
HISTORY_DB="$STATE_DIR/cache/history.sqlite3"
MIGRATION_JSON="/tmp/sbb-history-v4-migration.json"
MIGRATION_STDERR="/tmp/sbb-history-v4-migration.stderr.log"
MIGRATION_BACKUP=""
MIGRATION_REPORT=""
rollback(){
  echo "[deploy] New backend failed health checks. Rolling back application and catalog..."
  systemctl stop sports-big-board >/dev/null 2>&1 || true
  if [[ -n "$MIGRATION_BACKUP" && -f "$MIGRATION_BACKUP" ]]; then
    cp -f "$MIGRATION_BACKUP" "$HISTORY_DB"
    chown sportsbigboard:sportsbigboard "$HISTORY_DB"
    rm -f "${HISTORY_DB}-wal" "${HISTORY_DB}-shm"
    echo "[deploy] Restored pre-deploy history catalog: $MIGRATION_BACKUP"
  fi
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


# v4 catalog preflight is structural. Stop the old backend so SQLite is
# quiescent. Structurally healthy normalized catalogs are preserved and may get
# only a rollback snapshot for in-place relationship repair. Legacy/structurally
# invalid catalogs alone are reconstructed into a second database.
systemctl stop sports-big-board >/dev/null 2>&1 || true
ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"
if [[ -f "$HISTORY_DB" ]]; then
  # Run reconstruction in an explicit if-condition so an expected non-zero
  # audit result does NOT trigger the global ERR rollback trap before we can
  # print and preserve its reconciliation report.
  if runuser -u sportsbigboard -- env SBB_STATE_DIR="$STATE_DIR" \
      /usr/bin/python3 "$RELEASE_DIR/tools/ensure_history_v4.py" --state-dir "$STATE_DIR" \
      > "$MIGRATION_JSON" 2> >(tee "$MIGRATION_STDERR" >&2); then
    MIGRATION_RC=0
  else
    MIGRATION_RC=$?
  fi
  echo "[deploy] v4 catalog preflight exit code: $MIGRATION_RC"
  if [[ -s "$MIGRATION_JSON" ]]; then
    cat "$MIGRATION_JSON"
    MIGRATION_BACKUP="$(python3 -c 'import json; d=json.load(open("/tmp/sbb-history-v4-migration.json")); print(d.get("rollbackBackup", ""))' 2>/dev/null || true)"
    MIGRATION_REPORT="$(python3 -c 'import json; d=json.load(open("/tmp/sbb-history-v4-migration.json")); print(d.get("reconciliationReport", ""))' 2>/dev/null || true)"
  else
    echo "[deploy] ERROR: v4 preflight produced no structured JSON result."
  fi
  if [[ "$MIGRATION_RC" != "0" ]]; then
    echo "[deploy] v4 catalog preflight/reconstruction failed (exit $MIGRATION_RC)."
    if [[ -n "$MIGRATION_REPORT" && -f "$MIGRATION_REPORT" ]]; then
      echo "[deploy] Reconciliation report follows: $MIGRATION_REPORT"
      cat "$MIGRATION_REPORT" || true
    fi
    if [[ -s "$MIGRATION_JSON" ]]; then
      cp -f "$MIGRATION_JSON" "$STATE_DIR/backups/history-v4-last-failed-migration.json" || true
      chown sportsbigboard:sportsbigboard "$STATE_DIR/backups/history-v4-last-failed-migration.json" 2>/dev/null || true
      echo "[deploy] Preserved failed migration JSON at $STATE_DIR/backups/history-v4-last-failed-migration.json"
    fi
    trap - ERR
    rollback
    exit "$MIGRATION_RC"
  fi
else
  echo '[deploy] No historical catalog exists yet; v4 will initialize a fresh normalized catalog.'
fi
systemctl restart sports-big-board
# Normal startup is fast, but a structurally healthy catalog may still need a
# bounded in-place relationship repair before server.py opens port 8080.  As the
# catalog grows, that repair can legitimately exceed the old ~48 second window.
# Give it up to three minutes while still failing closed if the service dies.
healthy=0
LOCAL_HEALTH_ATTEMPTS=90
for ((attempt=1; attempt<=LOCAL_HEALTH_ATTEMPTS; attempt++)); do
  if curl -fsS --max-time 5 http://127.0.0.1:8080/api/status > /tmp/sbb-health.json; then healthy=1; break; fi
  if ! systemctl is-active --quiet sports-big-board; then
    echo "[deploy] Backend service exited while waiting for local health (attempt ${attempt}/${LOCAL_HEALTH_ATTEMPTS})."
    break
  fi
  if (( attempt % 15 == 0 )); then
    echo "[deploy] Backend still starting (${attempt}/${LOCAL_HEALTH_ATTEMPTS}); waiting for bounded catalog repair/startup..."
    journalctl -u sports-big-board --no-pager -n 12 || true
  fi
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
rm -f "$ARCHIVE" "$MIGRATION_JSON" "$MIGRATION_STDERR"
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
