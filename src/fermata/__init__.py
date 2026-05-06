"""Fermata governed-effect runtime seed package."""

from fermata.governed_effects import (
    EffectResult,
    EffectState,
    Intent,
    Proposal,
    Scope,
    Trace,
    evaluate_file_write,
)

CHORUS = "Agents may propose; only governed effects may commit."
__version__ = "0.1.0"

__all__ = [
    "CHORUS",
    "EffectResult",
    "EffectState",
    "Intent",
    "Proposal",
    "Scope",
    "Trace",
    "__version__",
    "evaluate_file_write",
]
