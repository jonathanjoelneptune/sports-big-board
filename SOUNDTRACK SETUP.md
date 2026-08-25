# Sports Big Board v4.1.27 — Soundtrack Setup

v4.1.27 adds a persistent site-level soundtrack without placing the ~400 MB MP3 library in GitHub. GitHub Pages ships the player and the 113-track manifest; the MP3 files live in a public-read Google Cloud Storage bucket named `<GCP_PROJECT_ID>-soundtrack`.

For the current project, the expected bucket is:

```text
gs://sportsbigboard-soundtrack
https://storage.googleapis.com/sportsbigboard-soundtrack
```

## One-time audio upload

You already downloaded these files:

```text
Sports-Big-Board-Soundtrack-Pack-1-of-6.zip
Sports-Big-Board-Soundtrack-Pack-2-of-6.zip
Sports-Big-Board-Soundtrack-Pack-3-of-6.zip
Sports-Big-Board-Soundtrack-Pack-4-of-6.zip
Sports-Big-Board-Soundtrack-Pack-5-of-6.zip
Sports-Big-Board-Soundtrack-Pack-6-of-6.zip
```

Open Google Cloud Shell, upload all six ZIPs into the same Cloud Shell directory, then from the v4.1.27 repository run:

```bash
gcloud config set project sportsbigboard
bash cloud/gcp/UPLOAD-SOUNDTRACK.sh Sports-Big-Board-Soundtrack-Pack-*.zip
```

The uploader:

- extracts all six packs into a temporary directory;
- validates all 113 MP3s against the manifest SHA-256 hashes;
- creates `gs://sportsbigboard-soundtrack` if it does not exist;
- enables public read for soundtrack objects only;
- configures GET/HEAD CORS for browser playback;
- uploads the normalized `tracks/*.mp3` library;
- uploads a copy of `manifest.json` for inspection;
- prints the final public soundtrack base URL.

The historical SQLite catalog, API credentials, VM state, and media caches are not touched.

## GitHub Pages wiring

No new GitHub variable is required for the normal `sportsbigboard` project. During the Pages build, v4.1.27 derives:

```text
https://storage.googleapis.com/<GCP_PROJECT_ID>-soundtrack
```

and writes it to `window.SBB_CONFIG.soundtrackBase`.

If a different bucket/CDN is desired later, add the optional repository variable:

```text
SBB_SOUNDTRACK_BASE_URL=https://your-cdn.example.com
```

That override changes only the audio origin.

## Local development

Local mode uses same-origin audio. Extract/copy the normalized files to:

```text
assets/soundtrack/tracks/
```

The folder is intentionally ignored by Git so local testing does not accidentally add hundreds of megabytes to the repository.

## Soundtrack behavior

- Soundtrack Mode is enabled by default on a first visit.
- Browser autoplay rules are respected. The first highlight click or other user gesture unlocks audio.
- Music starts during highlight startup/buffering and continues through highlight/date/game transitions.
- During actual highlight playback, the music ducks from the default 16% bed to roughly 10% so announcers stay intelligible.
- Pausing the highlight pauses the soundtrack.
- Track changes crossfade over 2.5 seconds.
- The 113-track library uses a unique shuffle bag: every enabled track is used before the bag is rebuilt, while CORE tracks are biased earlier in each fresh bag.
- Soundtrack enabled/disabled state, volume, current track, approximate track position, and remaining shuffle bag are persisted in `localStorage`.
- Search Priority suspends both highlight playback and soundtrack playback.
