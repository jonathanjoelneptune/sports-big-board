# Android setup — Sports Big Board v4.1.3

## Start

After extracting the ZIP:

```bash
cd ~/storage/downloads/sports-big-board-v4.1.3/sports-big-board-v4.1.3
bash START-ANDROID.sh
```

If Android extracts without the nested folder:

```bash
cd ~/storage/downloads/sports-big-board-v4.1.3
bash START-ANDROID.sh
```

Open `http://localhost:8080` in Chrome and keep Termux open.

## API keys are one-time per device

On first launch `setup_credentials.py` migrates recognized older Sports Big Board credentials and asks only for anything still missing:

- Highlightly
- YouTube Data API
- OpenAI

They are stored outside the downloaded release in:

```text
~/.sports-big-board/secrets.env
```

Every future Sports Big Board version on this Android device reuses that file. If a key was intentionally skipped, add it later from the **SETTINGS** tab in Sports Big Board; startup will not ask every time.

You can check configuration without showing key values:

```bash
python setup_credentials.py --status
```

## Verification

Android shared storage is normally `noexec`, so use:

```bash
bash VERIFY.sh
```

Node is optional. The Python suite covers the browser architecture/UI guards when Node is absent.

## Game Center behavior

Game Center is below the video on mobile in both portrait and landscape. It does not use PC side mode.

**Keep Video Visible** is ON by default. While scrolling Game Center, the video can remain sticky and shrink to preserve more room for stats. Turn the setting OFF if you prefer normal scrolling where the video eventually leaves the screen.

Game Centers are prepared and stored server-side in:

```text
~/.sports-big-board/cache/game-centers.sqlite3
```

## Timezone portability

The browser sends its date and UTC offset with live-score requests. Live-day cache policy does not depend on optional Python/Termux IANA tzdata.

## Optional blue-reel test

```text
http://localhost:8080/?forceBlue=1
```

Remove `?forceBlue=1` to return to normal programming.
