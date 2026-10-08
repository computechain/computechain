#!/usr/bin/env bash
# Preparation only; no SSH, account/firewall/service activation or stand migration.
set -euo pipefail
CPC_REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CPC_WORKSPACE_DIR="$(dirname -- "$CPC_REPO_DIR")"
CPC_PYTHON="${CPC_PYTHON:-$CPC_WORKSPACE_DIR/.tools/blockchain-venv/bin/python}"
exec "$CPC_PYTHON" "$CPC_REPO_DIR/scripts/multisite.py" "$@"
