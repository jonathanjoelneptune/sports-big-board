#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"

echo ""
echo "Sports Big Board v4.2.1 — Android"
echo "---------------------------------"

if ! command -v python >/dev/null 2>&1; then
  echo "Python is not installed. Run: pkg install python"
  exit 1
fi

# setup_credentials.py automatically migrates keys from older Sports Big Board
# releases into ~/.sports-big-board/secrets.env and only asks for missing keys.
python setup_credentials.py
python tools/ensure_history_v4.py

echo ""
echo "Starting: http://localhost:8080"
echo "Keep Termux open while Sports Big Board is running."
echo "Press Ctrl+C here to stop the server."
echo ""
python server.py
