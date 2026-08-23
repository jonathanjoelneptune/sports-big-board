# Sports Big Board v3.0.7 — Cloud Stage 1

v3.0.7 turns the existing local Sports Big Board server into an always-on Stage 1 cloud deployment without changing the core event/media/Game Center architecture.

## v3.0.7 one-push GitHub deployment

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

### One-time enablement for the existing Stage 1 VM

```bash
gcloud config set project sportsbigboard
bash cloud/gcp/ENABLE-GITHUB-AUTODEPLOY.sh jonathanjoelneptune/sports-big-board
```

The script creates a repository-restricted Google Workload Identity Federation trust and a dedicated deployment service account. It creates no long-lived Google service-account key. If GitHub CLI is already authenticated in Cloud Shell, it sets the repository variables automatically; otherwise it prints the exact values to paste once.

After that, future releases require no Cloud Shell command. Upload/commit the complete repository contents to `main` and watch the single **Deploy Sports Big Board** action.


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
2. Upload `sports-big-board-v3.0.7.zip` to Cloud Shell and extract it.
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
- start the 400-day historical backfill worker
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
4. Push v3.0.7 to `main`.

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
cd ~/storage/downloads/sports-big-board-v3.0.7/sports-big-board-v3.0.7
bash START-ANDROID.sh
```

Windows can continue using `START SPORTS BIG BOARD.bat`.
