# Sports Big Board v4.1.24 — Cloud Stage 1

v4.1.24 keeps the existing always-on Stage 1 deployment while replacing the historical media catalog with the normalized v4 baseline. Application releases remain immutable; the persistent disk is reconstructed separately and only after a passing audit.

## v4.1.24 one-push GitHub deployment

Stage 1 can now deploy both halves of Sports Big Board from one push to `main`. After a one-time keyless Google/GitHub trust setup, uploading the complete unzipped repository contents to the root of the GitHub repository is the entire release process.

The single `.github/workflows/deploy-pages.yml` workflow runs in this order:

```text
VERIFY
  -> deploy backend to the existing Compute Engine VM
  -> local + public backend health checks
  -> build the frontend with the cloud API URL
  -> deploy GitHub Pages
```

The backend deployment uses an immutable release directory and changes `/opt/sports-big-board/current` only for application code. `/var/lib/sports-big-board` and `/etc/sports-big-board/sbb.env` are never part of the release archive, so the historical database, Game Center cache, backups, and API credentials survive every GitHub deployment. If the new backend fails its local health check, the VM automatically restores the previous release before the GitHub workflow fails.

### First v4 deployment: audited catalog reconstruction

The first v4 deployment detects the existing v3 `cache/history.sqlite3` **before starting v4**. It stops the old backend, creates `backups/history-pre-v4-<timestamp>.sqlite3`, reconstructs a separate `cache/history-v4-rebuild.sqlite3`, writes a JSON reconciliation report under `backups/`, and installs the rebuilt database only when all integrity checks pass. The rebuild does not reacquire the internet catalog: it reuses already harvested source media, reclassifies scope/intent, re-proves GAME associations, moves daily/weekly packages to Silver, and quarantines ambiguity.

If v4 subsequently fails backend/public health checks, deployment restores both the previous application symlink **and the pre-v4 database backup**. The GitHub Pages job never publishes a v4 frontend against a failed backend/catalog deployment. A later deployment does **not** trust the schema marker alone: a generation-4 database must also be structurally complete and pass the hard integrity gate. If an interrupted transition leaves v4 tables beside preserved legacy rows, preflight automatically classifies it as an incomplete/invalid v4 catalog and reconstructs from those legacy rows. If the live file no longer contains enough legacy evidence, preflight falls back to the newest usable `backups/history-pre-v4-*.sqlite3` source rather than accepting or overwriting a damaged catalog.

### One-time enablement for the existing Stage 1 VM

```bash
gcloud config set project sportsbigboard
bash cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh jonathanjoelneptune/sports-big-board
```

The script creates a repository-restricted Google Workload Identity Federation trust and a dedicated deployment service account. It creates no long-lived Google service-account key. If GitHub CLI is already authenticated in Cloud Shell, it sets the repository variables automatically; otherwise it prints the exact values to paste once.

After that, future releases require no Cloud Shell command. Upload/commit the complete repository contents to `main` and watch the single **Deploy Sports Big Board** action.

### GitHub runner SSH transport

The GitHub deployment intentionally performs **one** `gcloud compute ssh` bootstrap. That call creates/installs one temporary 60-minute runner key and waits for the Compute Engine guest agent to accept it. Once the bootstrap prints `SSH READY`, deployment resolves the VM external IP and reuses that exact key with ordinary OpenSSH for the direct readiness probe, release upload, remote v4 catalog preflight/rebuild, health checks, and rollback shell. It does **not** invoke `gcloud compute scp` or a second `gcloud compute ssh`, so there is no second metadata/key-propagation cycle in the middle of a deployment.

A normal backend Action should progress through these milestones:

```text
[ssh] Bootstrap readiness attempt ...
[ssh] SSH READY as remote user ...
[ssh] Direct transport locked ...
[ssh] DIRECT SSH READY. No further gcloud SSH propagation will occur.
[upload] RELEASE UPLOAD COMPLETE.
[remote] Starting v4 deployment and catalog preflight over the established key...
... v4 reconstruction / audit output ...
[deploy] Backend v4.1.24-... is healthy.
```

If the initial bootstrap cannot propagate the key within the bounded retry window, the job exits before uploading a release and before touching the historical database. If direct-key reuse fails after bootstrap, it likewise exits before upload.


## Target architecture

```text
GitHub Pages (static UI)
        |
        | HTTPS /api/*
        v
Google Compute Engine VM
  - Caddy HTTPS gateway
  - Sports Big Board Python API
  - score/media/Game Center workers
  - historical backfill worker
        |
        v
Google persistent disk
  - history.sqlite3
  - game-centers.sqlite3
  - provider caches
  - daily SQLite backups
```

The browser no longer needs Termux or Windows CMD for normal use. Local launch scripts remain available as a development/fallback mode.

## One-time Google Cloud deployment

1. Open Google Cloud Console and launch **Cloud Shell**.
2. Upload `sports-big-board-v4.1.24.zip` to Cloud Shell and extract it.
3. Select the project that should own Sports Big Board:

```bash
gcloud config set project YOUR_PROJECT_ID
```

4. From the extracted release directory run:

```bash
bash cloud/gcp/CREATE-STAGE1.sh
```

The script will:

- enable Compute Engine
- reserve a static public IP
- create an Ubuntu 24.04 VM in `us-west2-b` by default
- create a separate persistent data disk
- open ports 80/443
- securely prompt for the existing Highlightly, YouTube, and OpenAI keys
- install Sports Big Board as a systemd service
- install Caddy and obtain HTTPS automatically
- mount the historical database outside release folders
- start the one-time historical seed through August 1, 2025 worker
- schedule daily SQLite backups
- print the backend HTTPS URL

The temporary Stage 1 hostname uses the reserved IP through `sslip.io`, for example:

```text
https://34-123-45-67.sslip.io
```

A custom `api.sportsbigboard.com` hostname can replace this later without changing the application architecture.

## GitHub Pages

After the VM script finishes it prints a value like:

```text
SBB_API_BASE_URL=https://34-123-45-67.sslip.io
```

In the GitHub repository:

1. **Settings → Secrets and variables → Actions → Variables**
2. Create repository variable `SBB_API_BASE_URL` with that HTTPS backend URL.
3. **Settings → Pages → Build and deployment → Source → GitHub Actions**.
4. Push v4.1.24 to `main`.

`.github/workflows/deploy-pages.yml` verifies the release, deploys the backend, verifies health, and only then publishes the static frontend. Backend code, SQLite databases, caches, and API credentials are never included in the Pages artifact.

## Persistent state

The VM service uses:

```text
/var/lib/sports-big-board/
  cache/history.sqlite3
  cache/game-centers.sqlite3
  cache/...
  backups/...
```

That directory is mounted from the separate Google persistent disk `sports-big-board-data`. Deploying a new release changes `/opt/sports-big-board/current` but does not replace the historical catalog.

## Updating the cloud release later

Normal releases are now automatic: upload/commit the complete new repository contents to the GitHub repository root on `main`. The **Deploy Sports Big Board** action handles backend and frontend deployment.

`bash cloud/gcp/DEPLOY-UPDATE.sh` remains available from Cloud Shell only as an emergency/manual fallback. Persistent databases and API credentials remain untouched.

## Useful server commands

SSH to the VM:

```bash
gcloud compute ssh sports-big-board --zone us-west2-b
```

Then:

```bash
sudo systemctl status sports-big-board
sudo journalctl -u sports-big-board -f
sudo systemctl status caddy
sudo systemctl list-timers sports-big-board-backup.timer
```

The API health endpoint is:

```text
https://YOUR_BACKEND_HOST/api/status
```

## Cloud security behavior

In cloud mode API credentials are environment-managed on the server. The public Settings panel can report whether each connection is configured, but it cannot read or replace the keys. The backend accepts browser CORS requests from its own HTTPS origin and GitHub Pages origins. API keys never enter the static frontend.

## Local development remains supported

Android / Termux:

```bash
cd ~/storage/downloads/sports-big-board-v4.1.24/sports-big-board-v4.1.24
bash START-ANDROID.sh
```

Windows can continue using `START SPORTS BIG BOARD.bat`.


### v4.1.24 catalog-preserving preflight

The GitHub deployment stops the backend before catalog preflight. For a structurally healthy v4 database, preflight **does not reconstruct or replace `history.sqlite3`** even when matcher/classifier relationships require repair. It optionally creates a pre-repair rollback snapshot, starts the new backend, repairs relationships in place, and requires the backend health check to pass. Deployment rollback restores the pre-deploy snapshot when one was created. Full reconstruction is reserved for structural/legacy catalog failures only.
