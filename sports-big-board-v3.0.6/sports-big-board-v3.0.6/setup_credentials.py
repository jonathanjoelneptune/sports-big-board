#!/usr/bin/env python3
"""One-time machine setup for Sports Big Board API credentials."""
from pathlib import Path
import argparse
from sbb.secrets import KEYS, get_secret, set_secrets, status, SECRETS_FILE, CONFIG_DIR
import json

LABELS={
    "HIGHLIGHTLY_API_KEY":"Highlightly API key (live scores / sports data)",
    "YOUTUBE_API_KEY":"YouTube Data API key (official highlight discovery)",
    "OPENAI_API_KEY":"OpenAI API key (optional editorial ranking)",
}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--status',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    current=status(root)
    state_file=CONFIG_DIR/'setup-state.json'
    try: setup_state=json.loads(state_file.read_text(encoding='utf-8'))
    except Exception: setup_state={}
    skipped=set(setup_state.get('skipped') or [])
    if args.status:
        for key in KEYS: print(f"{key}: {'configured' if current[key]['configured'] else 'missing'} ({current[key]['source']})")
        return 0
    print("Sports Big Board — one-time API setup")
    print("------------------------------------")
    print(f"Credentials are stored only on this computer in: {SECRETS_FILE}")
    updates={}
    for key in KEYS:
        if get_secret(key,root):
            print(f"[configured] {LABELS[key]}")
            continue
        if key in skipped:
            print(f"[not configured] {LABELS[key]} (skipped during initial setup; update it later in Settings)")
            continue
        print(f"\n[missing] {LABELS[key]}")
        value=input("Paste key, or press Enter to leave unconfigured: ").strip()
        if value:
            updates[key]=value; skipped.discard(key)
        else:
            skipped.add(key)
    if updates: set_secrets(updates)
    CONFIG_DIR.mkdir(parents=True,exist_ok=True)
    state_file.write_text(json.dumps({'skipped':sorted(skipped)},indent=2),encoding='utf-8')
    final=status(root)
    print("\nAPI setup status")
    for key in KEYS: print(f"  {LABELS[key]}: {'configured' if final[key]['configured'] else 'not configured'}")
    print("\nFuture Sports Big Board versions on this machine will reuse these settings automatically.")
    return 0

if __name__=='__main__': raise SystemExit(main())
