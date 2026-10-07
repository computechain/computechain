#!/usr/bin/env bash
# Use local dependencies and isolate the legacy suite fixed-name test directories.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(dirname -- "$SCRIPT_DIR")"
CPC_PYTHON="${CPC_PYTHON:-$WORKSPACE_DIR/.tools/blockchain-venv/bin/python}"
exec "$CPC_PYTHON" "$SCRIPT_DIR/scripts/test_suite.py" "$@"
