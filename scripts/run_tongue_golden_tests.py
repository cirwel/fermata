#!/usr/bin/env python3
"""Run v0 golden checks from the package module."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fermata.golden_checks import *  # noqa: F403
from fermata.golden_checks import main


if __name__ == "__main__":
    main()
