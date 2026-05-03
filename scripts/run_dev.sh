#!/usr/bin/env bash
# Dev runner — uses polling so no public URL is needed.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  echo "No .env found — copy .env.example to .env and fill it in."
  exit 1
fi

exec python -m app.main --polling
