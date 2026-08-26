#!/usr/bin/env bash
set -euo pipefail

# Sports Big Board v4.1.31 private soundtrack uploader.
# Accepts the six generated soundtrack ZIPs, one combined pool ZIP, or an already
# extracted Sports-Big-Board-Soundtrack-Pool directory. Public Access Prevention
# may remain enforced: the VM gets private objectViewer access and the browser
# uses signed GCS redirects with an authenticated proxy fallback.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_ID="${SBB_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
PROJECT_ID="${PROJECT_ID//[[:space:]]/}"
[[ -n "$PROJECT_ID" && "$PROJECT_ID" != "(unset)" ]] || { echo "Set SBB_PROJECT_ID or run: gcloud config set project YOUR_PROJECT"; exit 1; }
BUCKET="${SBB_SOUNDTRACK_BUCKET:-${PROJECT_ID}-soundtrack}"
REGION="${SBB_SOUNDTRACK_REGION:-us-west2}"
ZONE="${SBB_ZONE:-us-west2-b}"
VM_NAME="${SBB_VM_NAME:-sports-big-board}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

inputs=("$@")
if [[ ${#inputs[@]} -eq 0 ]]; then
  shopt -s nullglob
  inputs=(Sports-Big-Board-Soundtrack-Pack-*.zip Sports-Big-Board-Soundtrack-Pool.zip)
  shopt -u nullglob
fi
[[ ${#inputs[@]} -gt 0 ]] || { echo "Pass the soundtrack ZIP file(s) or extracted pool directory."; exit 1; }

for input in "${inputs[@]}"; do
  [[ -e "$input" ]] || { echo "Missing input: $input"; exit 1; }
  if [[ -d "$input" ]]; then
    cp -R "$input" "$TMP/"
  else
    case "$input" in
      *.zip) unzip -q -o "$input" -d "$TMP" ;;
      *) echo "Unsupported input: $input"; exit 1 ;;
    esac
  fi
done

POOL="$(find "$TMP" -type f -path '*/assets/soundtrack/manifest.json' -print -quit | xargs -r dirname | xargs -r dirname | xargs -r dirname)"
if [[ -z "$POOL" ]]; then
  POOL="$(find "$TMP" -type d -name 'Sports-Big-Board-Soundtrack-Pool' -print -quit || true)"
fi
[[ -n "$POOL" ]] || { echo "Could not locate Sports Big Board soundtrack manifest."; exit 1; }
MANIFEST="$POOL/assets/soundtrack/manifest.json"
TRACKS="$POOL/assets/soundtrack/tracks"
[[ -f "$MANIFEST" && -d "$TRACKS" ]] || { echo "Incomplete soundtrack pool under $POOL"; exit 1; }

python3 - "$MANIFEST" "$TRACKS" <<'PY'
import hashlib,json,pathlib,sys
manifest=pathlib.Path(sys.argv[1]); tracks=pathlib.Path(sys.argv[2]); data=json.loads(manifest.read_text())
rows=data.get('tracks') or []; missing=[]; bad=[]
for row in rows:
    p=tracks/pathlib.Path(row['file']).name
    if not p.exists(): missing.append(p.name); continue
    expected=str(row.get('sha256') or '')
    if expected:
        actual=hashlib.sha256(p.read_bytes()).hexdigest()
        if actual!=expected: bad.append(p.name)
if missing or bad:
    raise SystemExit(f'Soundtrack validation failed: missing={missing[:8]} bad_sha={bad[:8]}')
print(f'Validated {len(rows)} soundtrack tracks ({sum(p.stat().st_size for p in tracks.glob("*.mp3"))/1024/1024:.1f} MiB).')
PY

if ! gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1; then
  echo "Creating private gs://$BUCKET in $REGION ..."
  gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT_ID" --location="$REGION" --uniform-bucket-level-access
fi

# Public Access Prevention is fully compatible with v4.1.31 and should remain
# enforced when required by organization/project policy.
VM_SERVICE_ACCOUNT="$(gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" --format='value(serviceAccounts.email)' | head -1)"
[[ -n "$VM_SERVICE_ACCOUNT" ]] || { echo "Could not determine the $VM_NAME service account." >&2; exit 1; }
echo "Granting private soundtrack read access to VM service account: $VM_SERVICE_ACCOUNT"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$VM_SERVICE_ACCOUNT" --role=roles/storage.objectViewer >/dev/null

# signBlob lets the backend redirect browsers directly to short-lived signed GCS
# URLs. If this binding is not permitted, the backend automatically falls back to
# authenticated proxy streaming, so soundtrack playback still works.
if gcloud iam service-accounts add-iam-policy-binding "$VM_SERVICE_ACCOUNT" --project "$PROJECT_ID" \
    --member="serviceAccount:$VM_SERVICE_ACCOUNT" --role=roles/iam.serviceAccountTokenCreator >/dev/null 2>&1; then
  echo "Signed-URL capability enabled for $VM_SERVICE_ACCOUNT."
else
  echo "WARNING: Could not grant signBlob to the VM service account; v4.1.31 will use private proxy fallback." >&2
fi

gcloud services enable iamcredentials.googleapis.com storage.googleapis.com --project "$PROJECT_ID" >/dev/null
cat > "$TMP/cors.json" <<'JSON'
[
  {
    "origin": ["*"],
    "method": ["GET", "HEAD"],
    "responseHeader": ["Content-Type", "Content-Length", "Accept-Ranges", "Content-Range"],
    "maxAgeSeconds": 3600
  }
]
JSON
gcloud storage buckets update "gs://$BUCKET" --cors-file="$TMP/cors.json" >/dev/null

echo "Uploading soundtrack tracks ..."
gcloud storage rsync "$TRACKS" "gs://$BUCKET/tracks" --recursive
gcloud storage cp "$MANIFEST" "gs://$BUCKET/manifest.json" --cache-control="private,max-age=300"

echo
echo "Sports Big Board private soundtrack uploaded."
echo "Bucket: gs://$BUCKET"
echo "Tracks: $(gcloud storage ls "gs://$BUCKET/tracks/" | wc -l | tr -d ' ')"
echo "Public bucket access: NOT REQUIRED"
echo "v4.1.31 browser transport: backend -> signed GCS redirect -> private proxy fallback"
