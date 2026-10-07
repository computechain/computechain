#!/usr/bin/env python3
"""Current devnet load entrypoint; the old generator is archived as *_legacy.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from computechain.scripts.comet_load import main

if __name__ == "__main__":
    raise SystemExit(main())
