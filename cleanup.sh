#!/usr/bin/env bash
# Safe stop: never delete chain data or validator signing state.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start_test.sh" down "$@"
