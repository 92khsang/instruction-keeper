#!/usr/bin/env python3
"""Run every test module in this directory.

Run:  python3 tests/run_all.py

Equivalent to running each test file on its own; it exists so CI has one
command. Standard library only, Python 3.8+. Exits 0 when everything passes and
1 otherwise.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the repository

TESTS_DIR = Path(__file__).resolve().parent


def main() -> int:
    suite = unittest.TestLoader().discover(str(TESTS_DIR), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
