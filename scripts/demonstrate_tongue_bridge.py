#!/usr/bin/env python3
"""Demonstrate the tongue bridge end to end.

Walks four paths and prints the governed result for each:

1-3. Non-intent speech acts (need, claim, boundary) are parsed from the tongue
     and acknowledged by the runtime as PROPOSAL-state effects with a trace.
     Nothing is committed.
  4. An ``intend`` line is refused: effect intents must arrive as JSON and run
     through the full governed state machine, not be spoken as a one-liner.

Run: ``python3 scripts/demonstrate_tongue_bridge.py``
"""

from __future__ import annotations

import json
import sys

from fermata.tongue_bridge import TongueBridgeError, propose_from_utterance

UTTERANCES = [
    'need file.read target:"docs/charter.md" because:"verify before editing"',
    'claim "effect creation is not effect execution" evidence:[state_machine]',
    "boundary cannot commit effect:file.write reason:approval_missing offer:dry_run",
]

INTEND_LINE = 'intend file.write target:"note.txt"'


def main() -> int:
    """Print acknowledged proposals and the refused intent line."""

    records = []
    for line in UTTERANCES:
        result, trace = propose_from_utterance(line)
        records.append(
            {
                "utterance": line,
                "effect": result.to_record(),
                "trace": trace.to_record(),
            }
        )

    try:
        propose_from_utterance(INTEND_LINE)
    except TongueBridgeError as exc:
        records.append({"utterance": INTEND_LINE, "refused": str(exc)})
    else:  # pragma: no cover - the bridge must refuse spoken intents
        print("ERROR: bridge accepted a spoken intent line", file=sys.stderr)
        return 1

    print(json.dumps(records, indent=2, sort_keys=True))

    states = [r["effect"]["state"] for r in records if "effect" in r]
    if states != ["proposal", "proposal", "proposal"]:
        print(f"ERROR: unexpected states {states}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
