#!/usr/bin/env python3
"""Run current pytest suite in scratch storage, never in node/user directories."""
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent))
import pytest


def main():
    arguments = sys.argv[1:]
    if not arguments:
        arguments = [str(REPO / "tests"), "-q"]
    else:
        # Resolve actual path arguments before changing cwd; keep flags/-k expressions.
        arguments = [str(Path(arg.split("::", 1)[0]).resolve()) + ("::" + arg.split("::", 1)[1] if "::" in arg else "")
                     if not arg.startswith("-") and Path(arg.split("::", 1)[0]).exists() else arg for arg in arguments]
        if not any(not arg.startswith("-") and Path(arg.split("::", 1)[0]).exists() for arg in arguments):
            arguments.insert(0, str(REPO / "tests"))
    with tempfile.TemporaryDirectory(prefix="cpc-tests-") as scratch:
        os.chdir(scratch)
        return int(pytest.main([*arguments, "-p", "no:cacheprovider"]))


if __name__ == "__main__":
    raise SystemExit(main())
