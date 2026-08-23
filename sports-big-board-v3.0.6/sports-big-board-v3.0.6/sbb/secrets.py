"""Machine-local Sports Big Board secrets.

Secrets live outside release folders so every extracted version on the same machine
reuses the same credentials. Values are never returned to browser JavaScript.
"""
from pathlib import Path
import os
import tempfile
import threading

CONFIG_DIR = Path(os.environ.get("SBB_STATE_DIR") or (Path.home() / ".sports-big-board")).expanduser()
SECRETS_FILE = CONFIG_DIR / "secrets.env"
_LOCK = threading.RLock()
KEYS = ("HIGHLIGHTLY_API_KEY", "YOUTUBE_API_KEY", "OPENAI_API_KEY")
LEGACY_FILES = {
    "HIGHLIGHTLY_API_KEY": CONFIG_DIR / "highlightly-key",
    "YOUTUBE_API_KEY": CONFIG_DIR / "youtube-key",
    "OPENAI_API_KEY": CONFIG_DIR / "openai-key",
}


def _parse(text):
    out={}
    for raw in str(text or "").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key,value=line.split("=",1)
        key=key.strip(); value=value.strip()
        if key in KEYS: out[key]=value
    return out


def load_saved():
    try: return _parse(SECRETS_FILE.read_text(encoding="utf-8"))
    except Exception: return {}


def _atomic_write(values):
    CONFIG_DIR.mkdir(parents=True,exist_ok=True)
    lines=["# Sports Big Board machine-local credentials. Never commit or share this file."]
    for key in KEYS:
        if key in values: lines.append(f"{key}={str(values.get(key) or '').strip()}")
    content="\n".join(lines)+"\n"
    fd,tmp=tempfile.mkstemp(prefix="secrets-",suffix=".env.tmp",dir=str(CONFIG_DIR))
    os.close(fd)
    path=Path(tmp)
    try:
        path.write_text(content,encoding="utf-8")
        try: os.chmod(path,0o600)
        except Exception: pass
        path.replace(SECRETS_FILE)
        try: os.chmod(SECRETS_FILE,0o600)
        except Exception: pass
    finally:
        try:
            if path.exists(): path.unlink()
        except Exception: pass


def migrate_legacy(root=None):
    """Copy older per-key/per-release credentials into secrets.env once."""
    with _LOCK:
        saved=load_saved(); changed=False
        candidates=dict(LEGACY_FILES)
        if root:
            candidates["HIGHLIGHTLY_API_KEY_LOCAL"]=Path(root)/".highlightly-key"
        for name,path in candidates.items():
            key="HIGHLIGHTLY_API_KEY" if name.endswith("_LOCAL") else name
            if saved.get(key): continue
            try: value=path.read_text(encoding="utf-8").strip()
            except Exception: value=""
            if value:
                saved[key]=value; changed=True
        if changed: _atomic_write(saved)
        return saved


def get_secret(key, root=None):
    key=str(key or "").upper()
    if key not in KEYS: return ""
    env=(os.environ.get(key) or "").strip()
    if env: return env
    saved=migrate_legacy(root)
    return str(saved.get(key) or "").strip()


def set_secrets(updates):
    """Persist non-None replacements. Empty strings intentionally clear a key."""
    with _LOCK:
        current=load_saved()
        for key,value in dict(updates or {}).items():
            key=str(key or "").upper()
            if key not in KEYS or value is None: continue
            current[key]=str(value).strip()
        _atomic_write(current)
        return status()


def status(root=None):
    saved=migrate_legacy(root)
    out={}
    for key in KEYS:
        env=bool((os.environ.get(key) or "").strip())
        configured=env or bool(str(saved.get(key) or "").strip())
        out[key]={"configured":configured,"source":"environment" if env else ("machine" if configured else "missing")}
    return out
