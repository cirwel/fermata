"""Check versioned local-alpha release notes and tag checklist."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any


RELEASE_VERSION = "0.1.0"
RELEASE_TAG = f"v{RELEASE_VERSION}"
RELEASE_NOTES = Path("docs/releases/local-alpha-v0.1.0.md")
TAG_CHECKLIST = Path("docs/releases/local-alpha-v0.1.0-tag-checklist.md")
RELEASE_CANDIDATE_RECORD = Path(
    "references/release-candidates-v0/local-alpha-v0.1.0-rc1.json"
)
TAG_APPROVAL_PACKET = Path(
    "references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json"
)
VALIDATOR_COMMAND = "python3 scripts/validate_local_alpha.py"
RELEASE_CHECK_COMMAND = "python3 scripts/check_local_alpha_release_artifacts.py"
RELEASE_CANDIDATE_COMMAND = "python3 scripts/check_local_alpha_release_candidate.py"
RELEASE_CANDIDATE_RECORD_COMMAND = (
    "python3 scripts/check_local_alpha_release_candidate_record.py"
)
TAG_APPROVAL_PACKET_COMMAND = "python3 scripts/check_local_alpha_tag_approval_packet.py"


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


def require_contains(text: str, required: list[str], *, label: str) -> list[str]:
    """Assert every required fragment appears in text."""

    missing = [fragment for fragment in required if fragment not in text]
    require(not missing, f"{label}.missing:{missing}")
    return required


def checked_item_count(text: str) -> int:
    """Return the count of unchecked checklist items."""

    return sum(1 for line in text.splitlines() if line.startswith("- [ ] "))


def check_release_notes(notes: str, gate_names: list[str]) -> dict[str, Any]:
    """Validate the versioned local-alpha release notes."""

    required_fragments = [
        "# Fermata Local Alpha v0.1.0 Release Notes",
        "**Status:** Draft release packet",
        f"Package version: `{RELEASE_VERSION}`",
        f"Intended tag: `{RELEASE_TAG}`",
        f"Required validator: `{VALIDATOR_COMMAND}`",
        f"Release-candidate dry run: `{RELEASE_CANDIDATE_COMMAND}`",
        f"Release-candidate record: `{RELEASE_CANDIDATE_RECORD}`",
        f"Tag approval packet: `{TAG_APPROVAL_PACKET}`",
        f"Tag approval packet check: `{TAG_APPROVAL_PACKET_COMMAND}`",
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
        "file": str(RELEASE_NOTES),
        "required_fragments": len(required_fragments),
        "validator_gates_named": gate_names,
    }


def check_tag_checklist(checklist: str) -> dict[str, Any]:
    """Validate the local-alpha tag checklist."""

    required_fragments = [
        "# Fermata Local Alpha v0.1.0 Tag Checklist",
        "**Status:** Draft tag checklist",
        f"Package version: `{RELEASE_VERSION}`",
        f"Intended tag: `{RELEASE_TAG}`",
        f"Required validator: `{VALIDATOR_COMMAND}`",
        RELEASE_CHECK_COMMAND,
        RELEASE_CANDIDATE_COMMAND,
        RELEASE_CANDIDATE_RECORD_COMMAND,
        TAG_APPROVAL_PACKET_COMMAND,
        str(RELEASE_CANDIDATE_RECORD),
        str(TAG_APPROVAL_PACKET),
        "Release commit: `<fill-with-merged-main-commit-before-tagging>`",
        "GitHub Actions `ci / golden`",
        "maintainer approval",
        f"git tag -a {RELEASE_TAG}",
        f"git push origin {RELEASE_TAG}",
        "Do not retarget a\npushed tag",
    ]
    require_contains(checklist, required_fragments, label="tag_checklist")
    count = checked_item_count(checklist)
    require(count >= 10, "tag_checklist.required_checks_count")
    return {
        "file": str(TAG_CHECKLIST),
        "required_checks": count,
        "tag": RELEASE_TAG,
    }


def run_checks(*, root: Path | None = None) -> dict[str, Any]:
    """Run release artifact checks and return machine-readable evidence."""

    repo = root or repo_root()
    version = pyproject_version(repo)
    require(version == RELEASE_VERSION, f"version_mismatch:{version}")
    gate_names = local_alpha_gate_names(repo)
    notes = read_text(repo, RELEASE_NOTES)
    checklist = read_text(repo, TAG_CHECKLIST)
    read_text(repo, RELEASE_CANDIDATE_RECORD)
    read_text(repo, TAG_APPROVAL_PACKET)
    notes_result = check_release_notes(notes, gate_names)
    checklist_result = check_tag_checklist(checklist)
    return {
        "checks": {
            "package_version": version,
            "release_notes": notes_result,
            "tag_checklist": checklist_result,
            "validator_gates": gate_names,
        },
        "release_artifacts": "local-alpha-v0.1.0",
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
                    "release_artifacts": "local-alpha-v0.1.0",
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
