# Sports Big Board v4.1.28 Soundtrack Setup

v4.1.28 supports the 113-track Sports Big Board soundtrack while keeping the ~408 MiB MP3 library in a **private Google Cloud Storage bucket**. Public Access Prevention may remain enforced.

## Runtime architecture

GitHub Pages ships the soundtrack player and `assets/soundtrack/manifest.json`, but no MP3 files. For each track the browser requests:

`https://<sports-big-board-backend>/api/soundtrack/tracks/<track>.mp3`

The backend prefers a short-lived V4 signed Google Cloud Storage redirect. If the VM cannot call IAM `signBlob`, it transparently streams the same private object with its Compute Engine service-account access token. The fallback keeps the feature working without making the bucket public.

The expected bucket is:

`gs://sportsbigboard-soundtrack`

## One-time / repair setup

Place the six soundtrack ZIPs in one Cloud Shell directory and run from a v4.1.28 checkout:

```bash
gcloud config set project sportsbigboard
bash cloud/gcp/UPLOAD-SOUNDTRACK.sh ~/Soundtrack/Sports-Big-Board-Soundtrack-Pack-*.zip
```

The uploader:

- validates all 113 SHA-256 hashes;
- creates the bucket if needed;
- leaves Public Access Prevention intact;
- grants the Sports Big Board VM service account `roles/storage.objectViewer` on the soundtrack bucket;
- attempts to grant that VM service account `roles/iam.serviceAccountTokenCreator` on itself for signed URLs;
- configures CORS;
- uploads/synchronizes all 113 tracks and the manifest.

If the Token Creator grant is blocked, the uploader prints a warning. Playback still works through the authenticated private proxy fallback.

## Verification

After v4.1.28 is deployed:

```bash
curl -s https://<BACKEND>/api/soundtrack/status
```

The response should report 113 tracks, `private: true`, `preferredTransport: SIGNED-GCS`, and `fallbackTransport: PRIVATE-GCS-PROXY`.

A browser track request will expose `X-SBB-Soundtrack-Transport` as either `SIGNED-GCS` or `PRIVATE-GCS-PROXY`.

No catalog rebuild is required. Soundtrack state is independent of historical SQLite, Silver media, discovery workers, and Game Center.
