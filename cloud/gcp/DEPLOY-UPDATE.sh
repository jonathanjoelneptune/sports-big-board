#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
PROJECT_ID="${SBB_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${SBB_ZONE:-us-west2-b}"
VM_NAME="${SBB_VM_NAME:-sports-big-board}"
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then echo "Select a project with gcloud config set project ..."; exit 1; fi
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
tar --exclude='.git' --exclude='.pages-dist' --exclude='gha-creds-*.json' -czf "$TMP/release.tgz" -C "$ROOT" .
gcloud compute scp "$TMP/release.tgz" "$VM_NAME:/tmp/sbb-release.tgz" --zone "$ZONE" --project "$PROJECT_ID" >/dev/null
gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" --command "sudo env SBB_RELEASE_VERSION='$VERSION' bash -s" <<'REMOTE'
set -euo pipefail
VERSION="${SBB_RELEASE_VERSION:?}"
RELEASE_DIR="/opt/sports-big-board/releases/v${VERSION}"
rm -rf "$RELEASE_DIR"; mkdir -p "$RELEASE_DIR"
tar -xzf /tmp/sbb-release.tgz -C "$RELEASE_DIR"
chown -R root:root "$RELEASE_DIR"
ln -sfn "$RELEASE_DIR" /opt/sports-big-board/current
systemctl restart sports-big-board
rm -f /tmp/sbb-release.tgz
systemctl --no-pager --full status sports-big-board | head -30
REMOTE
