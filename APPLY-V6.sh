#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 tools/apply_v600_release.py
bash VERIFY.sh
printf '\nPASS: Sports Big Board v6.0.0 canonical shadow overlay applied and verified.\n'
