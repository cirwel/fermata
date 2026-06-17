"""Check versioned local-alpha release notes and tag checklist.

Version-aware: the release version is read from ``pyproject.toml`` and every
artifact path, tag name, and required fragment is derived from it. The checker
accepts either a pre-publication *candidate* release (notes status
``Release candidate`` / checklist status ``Active tag checklist``) or a
published *historical* release (``Published prerelease`` / ``Historical tag
checklist``), so the same gate validates a release before and after its tag
effect.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any


VALIDATOR_COMMAND = "python3 scripts/validate_local_alpha.py"
RELEASE_CHECK_COMMAND = "python3 scripts/check_local_alpha_release_artifacts.py"
RELEASE_CANDIDATE_COMMAND = "python3 scripts/check_local_alpha_release_candidate.py"
RELEASE_CANDIDATE_RECORD_COMMAND = (
    "python3 scripts/check_local_alpha_release_candidate_record.py"
)
TAG_APPROVAL_PACKET_COMMAND = "python3 scripts/check_local_alpha_tag_approval_packet.py"
TAG_PUBLICATION_PREFLIGHT_COMMAND = (
    "python3 scripts/check_local_alpha_tag_publication_preflight.py "
    "--approval-reference <approval-reference>"
)
ACCEPTED_NOTES_STATUS = ("Release candidate", "Published prerelease")
ACCEPTED_CHECKLIST_STATUS = ("Active tag checklist", "Historical tag checklist")


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def require(condition: bool, label: str) -> None:
    """Raise an assertion with a stable label when a check fails."""

    if not condition:
        raise AssertionError(label)


def read_text(root: Path, path: Path) -> str:
    """Read a UTF-8 text file relative to the repo root."""

    file_path = root / path
    require(file_path.exists(), f"missing:{path}")
    return file_path.read_text(encoding="utf-8")


def pyproject_version(root: Path) -> str:
    """Return the package version declared in pyproject.toml."""

    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    require(isinstance(version, str), "pyproject.version")
    return version


def local_alpha_gate_names(root: Path) -> list[str]:
    """Return validator gate names from the source tree."""

    sys.path.insert(0, str(root / "src"))
    from fermata.local_alpha_validator import gates

    return [gate.name for gate in gates()]


def require_any(text: str, options: tuple[str, ...], *, label: str) -> str:
    """Assert at least one option appears in text and return the first match."""

    for option in options:
        if option in text:
            return option
    raise AssertionError(f"{label}.missing_any:{list(options)}")


def require_contains(text: str, required: list[str], *, label: str) -> list[str]:
    """Assert every required fragment appears in text."""

    missing = [fragment for fragment in required if fragment not in text]
    require(not missing, f"{label}.missing:{missing}")
    return required


def checked_item_count(text: str) -> int:
    """Return the count of unchecked checklist items."""

    return sum(1 for line in text.splitlines() if line.startswith("- [ ] "))


def check_release_notes(
    notes: str,
    gate_names: list[str],
    *,
    version: str,
    tag: str,
    record_path: Path,
    packet_path: Path,
) -> dict[str, Any]:
    """Validate the versioned local-alpha release notes."""

    status = require_any(notes, ACCEPTED_NOTES_STATUS, label="release_notes.status")
    required_fragments = [
        f"# Fermata Local Alpha v{version} Release Notes",
        f"Package version: `{version}`",
        f"`{tag}`",
        f"Required validator: `{VALIDATOR_COMMAND}`",
        f"Release-candidate dry run: `{RELEASE_CANDIDATE_COMMAND}`",
        f"Release-candidate record: `{record_path}`",
        f"Tag approval packet: `{packet_path}`",
        f"Tag approval packet check: `{TAG_APPROVAL_PACKET_COMMAND}`",
        f"Tag publication preflight: `{TAG_PUBLICATION_PREFLIGHT_COMMAND}`",
        "proposal, intent, approval, and committed-effect boundaries",
        "hosted production readiness",
        "authenticated multi-user operation",
        "remote adapter safety",
        "cryptographic trace sealing",
        "general-purpose programming language",
    ]
    require_contains(notes, required_fragments, label="release_notes")
    missing_gates = [name for name in gate_names if name not in notes]
    require(not missing_gates, f"release_notes.gates_missing:{missing_gates}")
    return {
        "file": str(record_path),
        "status": status,
        "required_fragments": len(required_fragments),
        "validator_gates_named": gate_names,
    }


def check_tag_checklist(
    checklist: str,
    *,
    version: str,
    tag: str,
    record_path: Path,
    packet_path: Path,
) -> dict[str, Any]:
    """Validate the local-alpha tag checklist."""

    status = require_any(
        checklist, ACCEPTED_CHECKLIST_STATUS, label="tag_checklist.status"
    )
    required_fragments = [
        f"# Fermata Local Alpha v{version} Tag Checklist",
        f"Package version: `{version}`",
        f"`{tag}`",
        f"Required validator: `{VALIDATOR_COMMAND}`",
        RELEASE_CHECK_COMMAND,
        RELEASE_CANDIDATE_COMMAND,
        RELEASE_CANDIDATE_RECORD_COMMAND,
        TAG_APPROVAL_PACKET_COMMAND,
        TAG_PUBLICATION_PREFLIGHT_COMMAND,
        str(record_path),
        str(packet_path),
        "GitHub Actions `ci / golden`",
        "maintainer approval",
        f"git tag -a {tag}",
        f"git push origin {tag}",
        "Do not retarget",
        "retagging",
    ]
    require_contains(checklist, required_fragments, label="tag_checklist")
    count = checked_item_count(checklist)
    require(count >= 10, "tag_checklist.required_checks_count")
    return {
        "status": status,
        "required_checks": count,
        "tag": tag,
    }


def run_checks(*, root: Path | None = None) -> dict[str, Any]:
    """Run release artifact checks and return machine-readable evidence."""

    repo = root or repo_root()
    version = pyproject_version(repo)
    tag = f"v{version}"
    release_notes = Path(f"docs/releases/local-alpha-v{version}.md")
    tag_checklist = Path(f"docs/releases/local-alpha-v{version}-tag-checklist.md")
    record_path = Path(
        f"references/release-candidates-v0/local-alpha-v{version}-rc1.json"
    )
    packet_path = Path(
        "references/release-approvals-v0/"
        f"local-alpha-v{version}-tag-approval-packet.json"
    )

    gate_names = local_alpha_gate_names(repo)
    notes = read_text(repo, release_notes)
    checklist = read_text(repo, tag_checklist)
    read_text(repo, record_path)
    read_text(repo, packet_path)
    notes_result = check_release_notes(
        notes,
        gate_names,
        version=version,
        tag=tag,
        record_path=record_path,
        packet_path=packet_path,
    )
    checklist_result = check_tag_checklist(
        checklist,
        version=version,
        tag=tag,
        record_path=record_path,
        packet_path=packet_path,
    )
    return {
        "checks": {
            "package_version": version,
            "release_notes": notes_result,
            "tag_checklist": checklist_result,
            "validator_gates": gate_names,
        },
        "release_artifacts": f"local-alpha-v{version}",
        "status": "passed",
    }


def main() -> int:
    """CLI entry point."""

    try:
        result = run_checks()
    except AssertionError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "release_artifacts": "local-alpha",
                    "status": "failed",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
