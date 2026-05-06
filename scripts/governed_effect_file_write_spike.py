#!/usr/bin/env python3
"""Run the governed file-write adapter spike from the package module."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fermata.governed_effects import main


if __name__ == "__main__":
    main()
