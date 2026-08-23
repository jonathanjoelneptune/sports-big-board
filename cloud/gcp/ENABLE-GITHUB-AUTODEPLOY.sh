#!/usr/bin/env bash
set -euo pipefail
PROJECT_ID="${SBB_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
ZONE="${SBB_ZONE:-us-west2-b}"
VM_NAME="${SBB_VM_NAME:-sports-big-board}"
GITHUB_REPOSITORY="${1:-${SBB_GITHUB_REPOSITORY:-}}"
POOL_ID="${SBB_WIF_POOL_ID:-github-sbb}"
PROVIDER_ID="${SBB_WIF_PROVIDER_ID:-sports-big-board}"
SERVICE_ACCOUNT_ID="${SBB_DEPLOY_SERVICE_ACCOUNT_ID:-sports-big-board-github}"
if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
  echo "Select the Sports Big Board project first: gcloud config set project YOUR_PROJECT_ID"; exit 1
fi
if [[ -z "$GITHUB_REPOSITORY" || "$GITHUB_REPOSITORY" != */* ]]; then
  echo "Usage: bash cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh OWNER/REPOSITORY"; exit 1
fi
if ! gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "VM $VM_NAME was not found in $ZONE. Run CREATE-STAGE1.sh first."; exit 1
fi
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "Sports Big Board — GitHub one-push deployment setup"
echo "Project: $PROJECT_ID | Repo: $GITHUB_REPOSITORY | VM: $VM_NAME ($ZONE)"
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com compute.googleapis.com --project "$PROJECT_ID" >/dev/null
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[1/6] Creating GitHub deployment service account..."
  gcloud iam service-accounts create "$SERVICE_ACCOUNT_ID" --project "$PROJECT_ID" --display-name "Sports Big Board GitHub deployer"
else echo "[1/6] Deployment service account already exists."; fi
echo "[2/6] Granting Compute Engine deployment access..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" --role="roles/compute.instanceAdmin.v1" --condition=None >/dev/null
VM_SERVICE_ACCOUNT="$(gcloud compute instances describe "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" --format='value(serviceAccounts.email)' | head -1)"
if [[ -n "$VM_SERVICE_ACCOUNT" ]]; then
  gcloud iam service-accounts add-iam-policy-binding "$VM_SERVICE_ACCOUNT" --project "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" --role="roles/iam.serviceAccountUser" >/dev/null
fi
if ! gcloud iam workload-identity-pools describe "$POOL_ID" --location=global --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[3/6] Creating GitHub Workload Identity pool..."
  gcloud iam workload-identity-pools create "$POOL_ID" --project "$PROJECT_ID" --location=global --display-name="Sports Big Board GitHub"
else echo "[3/6] Workload Identity pool already exists."; fi
if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --workload-identity-pool="$POOL_ID" --location=global --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "[4/6] Creating repository-restricted GitHub OIDC provider..."
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --project "$PROJECT_ID" --location=global --workload-identity-pool="$POOL_ID" \
    --display-name="Sports Big Board repository" --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository == '$GITHUB_REPOSITORY' && assertion.ref == 'refs/heads/main'"
else echo "[4/6] GitHub OIDC provider already exists."; fi
POOL_NAME="$(gcloud iam workload-identity-pools describe "$POOL_ID" --project "$PROJECT_ID" --location=global --format='value(name)')"
PROVIDER_NAME="$(gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --project "$PROJECT_ID" --location=global --workload-identity-pool="$POOL_ID" --format='value(name)')"
echo "[5/6] Allowing only $GITHUB_REPOSITORY to impersonate the deployer..."
gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT_EMAIL" --project "$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_REPOSITORY}" >/dev/null
REGION="${ZONE%-*}"; ADDRESS_NAME="${SBB_ADDRESS_NAME:-sports-big-board-ip}"
PUBLIC_IP="$(gcloud compute addresses describe "$ADDRESS_NAME" --region "$REGION" --project "$PROJECT_ID" --format='value(address)' 2>/dev/null || true)"
API_URL=""; if [[ -n "$PUBLIC_IP" ]]; then API_URL="https://${PUBLIC_IP//./-}.sslip.io"; fi
echo "[6/6] GitHub deployment identity is ready."
echo ""
echo "Repository variables:"
echo "GCP_PROJECT_ID=$PROJECT_ID"
echo "GCP_WORKLOAD_IDENTITY_PROVIDER=$PROVIDER_NAME"
echo "GCP_DEPLOY_SERVICE_ACCOUNT=$SERVICE_ACCOUNT_EMAIL"
echo "SBB_GCP_ZONE=$ZONE"
echo "SBB_GCP_VM_NAME=$VM_NAME"
if [[ -n "$API_URL" ]]; then echo "SBB_API_BASE_URL=$API_URL"; fi
echo ""
echo "No long-lived Google service-account key is stored in GitHub."
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI authenticated; setting variables automatically..."
  gh variable set GCP_PROJECT_ID --repo "$GITHUB_REPOSITORY" --body "$PROJECT_ID"
  gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$GITHUB_REPOSITORY" --body "$PROVIDER_NAME"
  gh variable set GCP_DEPLOY_SERVICE_ACCOUNT --repo "$GITHUB_REPOSITORY" --body "$SERVICE_ACCOUNT_EMAIL"
  gh variable set SBB_GCP_ZONE --repo "$GITHUB_REPOSITORY" --body "$ZONE"
  gh variable set SBB_GCP_VM_NAME --repo "$GITHUB_REPOSITORY" --body "$VM_NAME"
  if [[ -n "$API_URL" ]]; then gh variable set SBB_API_BASE_URL --repo "$GITHUB_REPOSITORY" --body "$API_URL"; fi
  echo "GitHub repository variables configured automatically."
else
  echo "Paste the values above once under GitHub > Settings > Secrets and variables > Actions > Variables."
fi
echo "Future pushes: VERIFY -> BACKEND -> HEALTH CHECK -> GITHUB PAGES"
