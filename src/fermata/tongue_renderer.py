"""Render governed-effect tongue proposal records into readable text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def compact_evidence(record: dict[str, Any]) -> str:
    """Render evidence references compactly."""

    evidence = record.get("evidence") or []
    if not evidence:
        return ""
    return " Evidence: " + ", ".join(f"`{item}`" for item in evidence[:4]) + "."


def confidence_phrase(record: dict[str, Any]) -> str:
    """Render confidence without pretending it is calibrated truth."""

    confidence = record.get("confidence")
    if confidence is None:
        return ""
    return f" Confidence: {confidence:.2f}."


def render_need(record: dict[str, Any]) -> str:
    """Render a need/request proposal."""

    need = record.get("payload", {}).get("need", {})
    capability = need.get("capability", "a capability")
    target = need.get("target", "the target")
    reason = record.get("reason") or "continue safely"
    return f"I need `{capability}` on `{target}` so I can {reason}."


def render_claim(record: dict[str, Any]) -> str:
    """Render a public claim."""

    payload = record.get("payload", {})
    claim = payload.get("claim") or payload.get("utterance") or "a claim"
    return f"I can state this publicly: {claim}."


def render_doubt(record: dict[str, Any]) -> str:
    """Render a doubt without hidden chain-of-thought."""

    payload = record.get("payload", {})
    doubt = payload.get("doubt") or payload.get("utterance") or "this may need checking"
    reason = record.get("reason")
    if reason:
        return f"I'm holding a doubt: {doubt}. Reason: {reason}."
    return f"I'm holding a doubt: {doubt}."


def render_intend(record: dict[str, Any]) -> str:
    """Render an effect intent while preserving proposal/commit separation."""

    intent = record.get("intent") or {}
    adapter = intent.get("adapter", "unknown")
    operation = intent.get("operation", "unknown")
    target = intent.get("target", "unknown target")
    reason = record.get("reason") or "complete the requested step"
    return (
        f"I propose `{adapter}.{operation}` on `{target}` to {reason}. "
        "This is only a proposal until the governed runtime admits, verifies, "
        "approves, and commits it."
    )


def render_remember(record: dict[str, Any]) -> str:
    """Render a memory candidate."""

    payload = record.get("payload", {})
    candidate = payload.get("memory_candidate") or payload.get("utterance")
    candidate = candidate or "a memory candidate"
    lifespan = payload.get("lifespan", "unspecified")
    return f"Memory candidate ({lifespan}): {candidate}."


def render_boundary(record: dict[str, Any]) -> str:
    """Render a boundary/refusal/pause productively."""

    payload = record.get("payload", {})
    boundary = payload.get("boundary") or payload.get("utterance")
    boundary = boundary or "I cannot safely continue as-is"
    offer = payload.get("offer")
    if offer:
        return f"Boundary: {boundary}. I can offer: {offer}."
    return f"Boundary: {boundary}."


RENDERERS = {
    "need": render_need,
    "claim": render_claim,
    "doubt": render_doubt,
    "intend": render_intend,
    "remember": render_remember,
    "boundary": render_boundary,
}


def render_record(record: dict[str, Any]) -> str:
    """Render one proposal record."""

    speech_act = record.get("speech_act")
    renderer = RENDERERS.get(speech_act)
    if renderer is None:
        rendered = f"Unsupported speech act `{speech_act}`."
    else:
        rendered = renderer(record)
    return rendered + confidence_phrase(record) + compact_evidence(record)


def load_records(path: str | None) -> list[dict[str, Any]]:
    """Load JSON or JSONL records from a path or stdin."""

    text = Path(path).read_text() if path else sys.stdin.read()
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        return json.loads(stripped)
    if stripped.startswith("{") and "\n" not in stripped:
        return [json.loads(stripped)]
    return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def main() -> None:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="JSON or JSONL records; stdin if omitted")
    parser.add_argument("--limit", type=int, default=0, help="limit records rendered")
    args = parser.parse_args()

    records = load_records(args.path)
    if args.limit:
        records = records[: args.limit]
    for record in records:
        print(f"- {render_record(record)}")


if __name__ == "__main__":
    main()
