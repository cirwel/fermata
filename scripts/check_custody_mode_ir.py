#!/usr/bin/env python3
"""Drift guard for the custody_mode + profile extension added to the Governed
Effect IR (convergence step 1 — fermata becomes the canonical contract the
UNITARES Governed-Effect Plane targets).

Pins: custody_mode is optional, enum-constrained to {record_only, execute}, and
the profile/profile_ext extension hook accepts namespaced profile data without
relaxing the strict core. Run:  python3 scripts/check_custody_mode_ir.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "references" / "governed-effect-ir-v0.schema.json"
PACKAGED = ROOT / "src" / "fermata" / "reference_data" / "governed-effect-ir-v0.schema.json"

_BASE_INTENT = {
    "intent_id": "i_custody_check",
    "proposal_id": "p_custody_check",
    "adapter": "file",
    "operation": "write",
    "target": "sandbox/custody-check.txt",
    "input": {"content": "x"},
    "required_capability": "file.write",
    "idempotency_key": "k_custody_check",
}


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def main() -> int:
    failures: list[str] = []

    # The packaged copy must match the reference copy (it is what ships).
    if SCHEMA.read_text() != PACKAGED.read_text():
        failures.append("packaged reference_data schema is out of sync with references/ copy")

    v = _validator()

    def valid(doc) -> bool:
        return not list(v.iter_errors(doc))

    # custody_mode is OPTIONAL — a record without it still validates (back-compat).
    if not valid(_BASE_INTENT):
        failures.append("intent without custody_mode should validate (custody_mode must be optional)")

    # both modes validate, with a profile + namespaced profile_ext.
    for mode in ("record_only", "execute"):
        doc = {**_BASE_INTENT, "custody_mode": mode, "profile": "unitares",
               "profile_ext": {"unitares_effect_type": "agent_spawn", "required_tier": "strong"}}
        if not valid(doc):
            failures.append(f"intent with custody_mode={mode} + profile should validate")

    # an invalid custody_mode value is rejected.
    if valid({**_BASE_INTENT, "custody_mode": "bogus"}):
        failures.append("invalid custody_mode value should be rejected")

    # profile_ext is a namespaced escape hatch; the strict core still rejects an
    # UNKNOWN top-level field (additionalProperties: false holds).
    if valid({**_BASE_INTENT, "unitares_tier": "strong"}):
        failures.append("unknown top-level field should be rejected — profile data belongs in profile_ext")

    if failures:
        print(json.dumps({"status": "failed", "failures": failures}, indent=2))
        return 1
    print(json.dumps({"status": "passed", "checks": ["optional", "both_modes", "enum_constrained",
                                                      "strict_core_preserved", "packaged_in_sync"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
