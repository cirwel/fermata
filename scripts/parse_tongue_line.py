#!/usr/bin/env python3
"""Run the v0 tongue parser from the package module."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fermata.tongue_parser import *  # noqa: F403
from fermata.tongue_parser import main


if __name__ == "__main__":
    main()
