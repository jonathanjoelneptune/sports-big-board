# Windows setup — Sports Big Board v4.1.19

## Normal launch

Double-click:

```text
START SPORTS BIG BOARD.bat
```

The launcher finds `python` or the Windows `py` launcher, runs one-time API setup, opens `http://localhost:8080`, and starts the local server.

## API keys are one-time per PC

Sports Big Board stores credentials outside the extracted version folder in:

```text
%USERPROFILE%\.sports-big-board\secrets.env
```

The first setup checks all three integrations:

- Highlightly API key
- YouTube Data API key
- OpenAI API key

Once stored, v4.1.19, v2.7, v3.0, etc. on that same Windows account reuse the file automatically. You should not need to paste keys again after each upgrade.

If an older Sports Big Board release has a recognized saved key, setup migrates it automatically where possible.

A different device (for example Android vs PC) has its own secrets file. Sports Big Board does not transmit keys between devices. Enter or securely copy them once to the PC.

Check status without displaying secrets:

```text
python setup_credentials.py --status
```

You can also add/replace missing keys later from **SETTINGS** in the browser. The UI shows only CONFIGURED / NOT SET; the server never sends saved secret values back to JavaScript.

## Manual start

```text
python setup_credentials.py
python server.py
```

If `python` is not recognized but the Python launcher is installed:

```text
py setup_credentials.py
py server.py
```

## Persistent local data

Machine-level Sports Big Board state lives below:

```text
%USERPROFILE%\.sports-big-board\
```

including API settings and the persistent Game Center/media caches. Extracting a new release does not erase those machine-level settings.
