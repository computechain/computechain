#!/usr/bin/env bash
# Script to run tests from project directory
# Usage: ./run_tests.sh [pytest args]

set -euo pipefail

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

# Change to parent directory
cd "$PARENT_DIR"

# Run pytest with all provided arguments
# If no arguments provided, run all tests
if [ $# -eq 0 ]; then
    echo "Running all tests..."
    python3 -m pytest "$PROJECT_NAME/tests/" -v
else
    echo "Running tests with custom args: $*"
    python3 -m pytest "$@"
fi
