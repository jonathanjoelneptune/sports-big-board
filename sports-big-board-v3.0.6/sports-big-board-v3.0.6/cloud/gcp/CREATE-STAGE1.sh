#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
PROJECT_ID="${SBB_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${SBB_ZONE:-us-west2-b}"
REGION="${SBB_REGION:-${ZONE%-*}}"
VM_NAME="${SBB_VM_NAME:-sports-big-board}"
MACHINE_TYPE="${SBB_MACHINE_TYPE:-e2-medium}"
DATA_DISK="${SBB_DATA_DISK:-sports-big-board-data}"
DATA_DISK_SIZE="${SBB_DATA_DISK_SIZE:-30GB}"
ADDRESS_NAME="${SBB_ADDRESS_NAME:-sports-big-board-ip}"
FIREWALL_NAME="${SBB_FIREWALL_NAME:-sports-big-board-web}"

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "No Google Cloud project is selected."
  echo "Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo ""
echo "Sports Big Board v${VERSION} — Google Cloud Stage 1"
echo "--------------------------------------------------"
echo "Project:  $PROJECT_ID"
echo "Zone:     $ZONE"
echo "VM:       $VM_NAME ($MACHINE_TYPE)"
echo "Data disk:$DATA_DISK ($DATA_DISK_SIZE, persistent)"
echo ""

gcloud services enable compute.googleapis.com --project "$PROJECT_ID" >/dev/null

if ! gcloud compute addresses describe "$ADDRESS_NAME" --region "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[1/7] Reserving a static public IP..."
  gcloud compute addresses create "$ADDRESS_NAME" --region "$REGION" --project "$PROJECT_ID"
else
  echo "[1/7] Static public IP already exists."
fi
PUBLIC_IP="$(gcloud compute addresses describe "$ADDRESS_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(address)')"
PUBLIC_HOST="${PUBLIC_IP//./-}.sslip.io"

if ! gcloud compute disks describe "$DATA_DISK" --zone "$ZONE" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[2/7] Creating persistent Sports Big Board data disk..."
  gcloud compute disks create "$DATA_DISK" --size "$DATA_DISK_SIZE" --type pd-balanced --zone "$ZONE" --project "$PROJECT_ID"
else
  echo "[2/7] Persistent data disk already exists."
fi

if ! gcloud compute firewall-rules describe "$FIREWALL_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[3/7] Opening HTTP/HTTPS for the web gateway..."
  gcloud compute firewall-rules create "$FIREWALL_NAME" --project "$PROJECT_ID" \
    --network default --allow tcp:80,tcp:443 --target-tags sbb-web --description "Sports Big Board Stage 1 HTTPS"
else
  echo "[3/7] Web firewall rule already exists."
fi

if ! gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[4/7] Creating always-on Sports Big Board VM..."
  gcloud compute instances create "$VM_NAME" \
    --project "$PROJECT_ID" --zone "$ZONE" --machine-type "$MACHINE_TYPE" \
    --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
    --boot-disk-size 20GB --boot-disk-type pd-balanced \
    --address "$PUBLIC_IP" --tags sbb-web \
    --disk "name=$DATA_DISK,device-name=$DATA_DISK,mode=rw,boot=no,auto-delete=no"
else
  echo "[4/7] VM already exists."
  if ! gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" --format='value(disks.deviceName)' | tr ';' '\n' | grep -qx "$DATA_DISK"; then
    gcloud compute instances attach-disk "$VM_NAME" --disk "$DATA_DISK" --device-name "$DATA_DISK" --zone "$ZONE" --project "$PROJECT_ID"
  fi
fi

TMPDIR_LOCAL="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT
SECRETS="$TMPDIR_LOCAL/sbb.env"
umask 077

read_secret(){
  local env_name="$1" label="$2" value="${!env_name:-}"
  if [[ -z "$value" ]]; then
    read -r -s -p "$label (press Enter to leave unset): " value || true
    echo ""
  fi
  printf '%s=%s\n' "$env_name" "$value" >> "$SECRETS"
}

echo "[5/7] Preparing server credentials. They are uploaded directly to the VM and are never placed in GitHub Pages."
: > "$SECRETS"
read_secret HIGHLIGHTLY_API_KEY "Highlightly API key"
read_secret YOUTUBE_API_KEY "YouTube Data API key"
read_secret OPENAI_API_KEY "OpenAI API key"

TARBALL="$TMPDIR_LOCAL/sports-big-board-v${VERSION}.tgz"
tar --exclude='.git' --exclude='.pages-dist' -czf "$TARBALL" -C "$ROOT" .

echo "[6/7] Uploading v${VERSION} to the VM..."
for attempt in {1..12}; do
  if gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" --command 'echo ssh-ready' >/dev/null 2>&1; then break; fi
  if [[ "$attempt" == "12" ]]; then echo "SSH did not become ready."; exit 1; fi
  sleep 5
done

gcloud compute scp "$TARBALL" "$VM_NAME:/tmp/sbb-release.tgz" --zone "$ZONE" --project "$PROJECT_ID" >/dev/null
gcloud compute scp "$SECRETS" "$VM_NAME:/tmp/sbb-secrets.env" --zone "$ZONE" --project "$PROJECT_ID" >/dev/null

echo "[7/7] Installing the always-on backend, persistent catalog, HTTPS, and backups..."
gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" --command "\
  rm -rf /tmp/sbb-install && mkdir -p /tmp/sbb-install && \
  tar -xzf /tmp/sbb-release.tgz -C /tmp/sbb-install && \
  sudo bash /tmp/sbb-install/cloud/vm/INSTALL-STAGE1.sh '$PUBLIC_HOST' '$DATA_DISK' && \
  rm -rf /tmp/sbb-install /tmp/sbb-release.tgz /tmp/sbb-secrets.env"

API_URL="https://${PUBLIC_HOST}"
echo ""
echo "Stage 1 backend is online."
echo "  Backend:     $API_URL"
echo "  Health:      $API_URL/api/status"
echo "  Persistent:  Google persistent disk $DATA_DISK"
echo ""
echo "For GitHub Pages, set this repository variable:"
echo "  SBB_API_BASE_URL=$API_URL"
echo ""
echo "Then enable Settings > Pages > Source: GitHub Actions and push v${VERSION}."
echo "The included workflow will publish only the static frontend; API keys and databases stay on the VM."
