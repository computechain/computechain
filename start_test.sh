#!/usr/bin/env bash
# Current CometBFT operator entrypoint; no resets, global wallets or broad pkill.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(dirname -- "$SCRIPT_DIR")"
CPC_PYTHON="${CPC_PYTHON:-$WORKSPACE_DIR/.tools/blockchain-venv/bin/python}"
if [[ ! -x "$CPC_PYTHON" ]]; then
  echo "Install local dependencies first: python3 $SCRIPT_DIR/scripts/setup_comet.py" >&2
  exit 1
fi
exec "$CPC_PYTHON" "$SCRIPT_DIR/scripts/devnet.py" "$@"
