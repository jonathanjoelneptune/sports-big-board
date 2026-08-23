#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 setup_credentials.py
python3 tools/ensure_history_v4.py
python3 server.py
