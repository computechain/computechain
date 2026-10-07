#!/usr/bin/env bash
# Show the current Grafana URL; use SSH tunneling on a headless host.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/start_test.sh" status "$@"
