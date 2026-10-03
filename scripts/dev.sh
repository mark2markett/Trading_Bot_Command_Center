#!/usr/bin/env bash
# Linux/macOS twin of dev.ps1
set -e
cd "$(dirname "$0")/.."
PYTHONPATH=cc_sdk:cc_server python -m cc_server.main --reload &
cd cc_web && npm run dev
