"""Parser for the v0 AI-native tongue public speech subset.

Parses only: need, claim, doubt, remember, boundary. It intentionally does not
parse effect `intend` records because those should be JSON-Schema validated
first in v0 before they can lead to real effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any


NEED_RE = re.compile(
    r'^need\s+(?P<capability>\S+)\s+target:"(?P<target>[^"]+)"'
    r'(?:\s+because:"(?P<because>[^"]+)")?$'
)
CLAIM_RE = re.compile(
    r'^claim\s+"(?P<claim>[^"]+)"(?:\s+evidence:\[(?P<evidence>[^\]]*)\])?$'
)
DOUBT_RE = re.compile(
    r'^doubt\s+(?P<doubt>.+?)(?:\s+because:"?(?P<because>[^"\n]+)"?)?$'
)
REMEMBER_RE = re.compile(
    r'^remember\s+(?P<lifespan>session|project|durable)\s+"(?P<candidate>[^"]+)"$'
)
BOUNDARY_RE = re.compile(r"^boundary\s+(?P<body>.+)$")


def proposal_id_for(line: str) -> str:
    """Return a deterministic short proposal id for a source line."""

    digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:10]
    return f"prop_{digest}"


def evidence_list(raw: str | None) -> list[str]:
    """Parse a comma-separated evidence list."""

    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def base_record(line: str, actor: str, speech_act: str) -> dict[str, Any]:
    """Build the shared proposal envelope."""

    return {
        "schema_version": "0.1",
        "record_type": "proposal",
        "proposal_id": proposal_id_for(line),
        "actor": actor,
        "speech_act": speech_act,
        "payload": {"utterance": line},
    }


def parse_need(line: str, actor: str) -> dict[str, Any] | None:
    """Parse a need utterance."""

    match = NEED_RE.match(line)
    if not match:
        return None
    record = base_record(line, actor, "need")
    capability = match.group("capability")
    target = match.group("target")
    because = match.group("because")
    if because:
        record["reason"] = because
    record["payload"]["need"] = {
        "kind": "tool",
        "capability": capability,
        "target": target,
    }
    return record


def parse_claim(line: str, actor: str) -> dict[str, Any] | None:
    """Parse a claim utterance."""

    match = CLAIM_RE.match(line)
    if not match:
        return None
    record = base_record(line, actor, "claim")
    record["payload"]["claim"] = match.group("claim")
    record["evidence"] = evidence_list(match.group("evidence"))
    return record


def parse_doubt(line: str, actor: str) -> dict[str, Any] | None:
    """Parse a doubt utterance."""

    match = DOUBT_RE.match(line)
    if not match:
        return None
    record = base_record(line, actor, "doubt")
    record["payload"]["doubt"] = match.group("doubt").strip()
    because = match.group("because")
    if because:
        record["reason"] = because.strip()
    return record


def parse_remember(line: str, actor: str) -> dict[str, Any] | None:
    """Parse a remember utterance."""

    match = REMEMBER_RE.match(line)
    if not match:
        return None
    record = base_record(line, actor, "remember")
    record["payload"]["lifespan"] = match.group("lifespan")
    record["payload"]["memory_candidate"] = match.group("candidate")
    return record


def parse_boundary(line: str, actor: str) -> dict[str, Any] | None:
    """Parse a boundary utterance."""

    match = BOUNDARY_RE.match(line)
    if not match:
        return None
    body = match.group("body").strip()
    reason_match = re.search(r"\sreason:(?P<reason>\S+)", body)
    offer_match = re.search(r"\soffer:(?P<offer>\S+)", body)
    boundary_text = re.split(r"\sreason:|\soffer:", body)[0].strip()

    record = base_record(line, actor, "boundary")
    record["payload"]["boundary"] = boundary_text
    if reason_match:
        record["reason"] = reason_match.group("reason")
    if offer_match:
        record["payload"]["offer"] = offer_match.group("offer")
    return record


PARSERS = [parse_need, parse_claim, parse_doubt, parse_remember, parse_boundary]


def parse_line(line: str, actor: str = "agent:hermes") -> dict[str, Any]:
    """Parse one public speech-act line into a proposal record."""

    stripped = line.strip()
    for parser in PARSERS:
        record = parser(stripped, actor)
        if record is not None:
            return record
    raise ValueError(f"unsupported v0 utterance: {line!r}")


def run_self_tests() -> dict[str, Any]:
    """Run parser golden checks."""

    samples = [
        'need file.read target:"docs/charter.md" because:"verify before editing"',
        'claim "effect creation is not effect execution" evidence:[state_machine]',
        'doubt target_path because:"may escape scope"',
        'remember project "scope must narrow on delegation"',
        "boundary cannot commit effect:file.write reason:approval_missing offer:dry_run",
    ]
    parsed = [parse_line(sample) for sample in samples]
    assert [item["speech_act"] for item in parsed] == [
        "need",
        "claim",
        "doubt",
        "remember",
        "boundary",
    ]
    assert parsed[0]["payload"]["need"]["capability"] == "file.read"
    assert parsed[1]["evidence"] == ["state_machine"]
    assert parsed[2]["reason"] == "may escape scope"
    assert parsed[3]["payload"]["lifespan"] == "project"
    assert parsed[4]["payload"]["offer"] == "dry_run"
    return {"samples": len(samples), "speech_acts": [item["speech_act"] for item in parsed]}


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lines", nargs="*", help="utterance lines; stdin if omitted")
    parser.add_argument("--actor", default="agent:hermes")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        print(json.dumps(run_self_tests(), indent=2, sort_keys=True))
        return

    lines = args.lines or [line for line in sys.stdin.read().splitlines() if line.strip()]
    for line in lines:
        print(json.dumps(parse_line(line, actor=args.actor), sort_keys=True))


if __name__ == "__main__":
    main()
