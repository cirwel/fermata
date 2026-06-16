#!/usr/bin/env python3
"""Run every current local alpha readiness gate."""

from __future__ import annotations

from fermata.local_alpha_validator import main


if __name__ == "__main__":
    raise SystemExit(main())
