"""Check the local-alpha maintainer tag approval packet."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


PACKET_ID = "local-alpha-v0.1.0-tag-approval-packet"
PACKET_RECORD = Path(
    "references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json"
)
PACKAGE_VERSION = "0.1.0"
INTENDED_TAG = "v0.1.0"
RELEASE_NOTES = Path("docs/releases/local-alpha-v0.1.0.md")
TAG_CHECKLIST = Path("docs/releases/local-alpha-v0.1.0-tag-checklist.md")
RELEASE_CANDIDATE_RECORD = Path(
    "references/release-candidates-v0/local-alpha-v0.1.0-rc1.json"
)
TAG_COMMANDS = [
    'git tag -a v0.1.0 -m "Fermata local alpha v0.1.0"',
    "git push origin v0.1.0",
]
REQUIRED_LAST_MINUTE_COMMANDS = [
    "git status --short --branch",
    "git rev-parse HEAD origin/main",
    "git tag --list v0.1.0",
    "python3 scripts/check_local_alpha_release_artifacts.py",
    "python3 scripts/check_local_alpha_release_candidate.py",
    "python3 scripts/check_local_alpha_release_candidate_record.py",
    "python3 scripts/check_local_alpha_tag_approval_packet.py",
    "python3 scripts/check_local_alpha_tag_publication_preflight.py --approval-reference <approval-reference>",
    "python3 scripts/validate_local_alpha.py",
]
REQUIRED_MANUAL_RECHECKS = [
    "Confirm GitHub Actions `ci / golden` passed on the exact release commit.",
    "Confirm maintainer approval reference is present before running tag commands.",
]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def require(condition: bool, label: str) -> None:
    """Raise an assertion with a stable label when a check fails."""

    if not condition:
        raise AssertionError(label)


def load_json(root: Path, path: Path) -> dict[str, Any]:
    """Load a JSON object from a repo-relative path."""

    file_path = root / path
    require(file_path.exists(), f"missing:{path}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"{path}.not_object")
    return data


def git_succeeds(root: Path, args: list[str]) -> bool:
    """Return whether a Git check command succeeds."""

    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def require_string(value: Any, label: str) -> str:
    """Return a string value or fail."""

    require(isinstance(value, str) and bool(value), label)
    return value


def require_string_list(value: Any, label: str) -> list[str]:
    """Return a list of strings or fail."""

    require(isinstance(value, list), f"{label}.type")
    items: list[str] = []
    for index, item in enumerate(value):
        require(isinstance(item, str) and bool(item), f"{label}.{index}.type")
        items.append(item)
    return items


def check_release_commit_requirement(
    record: dict[str, Any], root: Path
) -> dict[str, Any]:
    """Validate the release commit binding rule."""

    prepared_from = require_string(record.get("prepared_from_commit"), "prepared_from")
    require(COMMIT_RE.match(prepared_from) is not None, "prepared_from.format")
    commit_available = git_succeeds(
        root, ["cat-file", "-e", f"{prepared_from}^{{commit}}"]
    )
    commit_is_ancestor = None
    if commit_available:
        commit_is_ancestor = git_succeeds(
            root, ["merge-base", "--is-ancestor", prepared_from, "HEAD"]
        )
        require(commit_is_ancestor, "prepared_from.ancestor")

    requirement = record.get("release_commit_requirement")
    require(isinstance(requirement, dict), "release_commit_requirement.type")
    require(requirement.get("branch") == "main", "release_commit_requirement.branch")
    require(
        requirement.get("must_equal_remote_ref") == "origin/main",
        "release_commit_requirement.remote",
    )
    require(
        requirement.get("release_commit_placeholder")
        == "<fill-with-merged-main-commit-before-tagging>",
        "release_commit_requirement.placeholder",
    )
    return {
        "available_in_checkout": commit_available,
        "is_ancestor_of_head": commit_is_ancestor,
        "prepared_from_commit": prepared_from,
    }


def check_requested_effect(record: dict[str, Any], root: Path) -> dict[str, str]:
    """Validate requested source-control effect metadata."""

    effect = record.get("requested_effect")
    require(isinstance(effect, dict), "requested_effect.type")
    require(effect.get("effect_kind") == "source_control.tag", "requested_effect.kind")
    require(
        effect.get("operation") == "create_and_push_annotated_tag",
        "requested_effect.operation",
    )
    require(effect.get("tag_name") == INTENDED_TAG, "requested_effect.tag_name")
    require(effect.get("target_remote") == "origin", "requested_effect.remote")
    require(
        effect.get("tag_message") == "Fermata local alpha v0.1.0",
        "requested_effect.tag_message",
    )

    paths = {
        "release_notes": RELEASE_NOTES,
        "tag_checklist": TAG_CHECKLIST,
        "release_candidate_record": RELEASE_CANDIDATE_RECORD,
    }
    for field, path in paths.items():
        require(effect.get(field) == str(path), f"requested_effect.{field}")
        require((root / path).exists(), f"requested_effect.{field}.missing")
    return {
        "effect_kind": str(effect.get("effect_kind")),
        "operation": str(effect.get("operation")),
        "tag_name": str(effect.get("tag_name")),
    }


def check_approval(record: dict[str, Any]) -> dict[str, Any]:
    """Validate that the packet is not itself approval."""

    require(record.get("status") == "pre_effect_packet", "status")
    require(record.get("approval_status") == "not_granted", "approval_status")
    approval = record.get("maintainer_approval")
    require(isinstance(approval, dict), "maintainer_approval.type")
    require(approval.get("required") is True, "maintainer_approval.required")
    require(approval.get("status") == "not_granted", "maintainer_approval.status")
    require(approval.get("approval_reference") is None, "approval_reference")
    require(approval.get("approved_by") is None, "approved_by")
    require(approval.get("approved_at") is None, "approved_at")
    return {"required": True, "status": "not_granted"}


def check_commands(record: dict[str, Any]) -> dict[str, Any]:
    """Validate exact tag commands and preflight rechecks."""

    commands = require_string_list(
        record.get("exact_commands_after_approval"), "exact_commands_after_approval"
    )
    require(commands == TAG_COMMANDS, "tag_commands")

    rechecks = record.get("last_minute_rechecks")
    require(isinstance(rechecks, list), "last_minute_rechecks.type")
    command_names: list[str] = []
    for index, row in enumerate(rechecks):
        require(isinstance(row, dict), f"last_minute_rechecks.{index}.type")
        command = require_string(row.get("command"), f"last_minute_rechecks.{index}")
        require_string(row.get("expect"), f"last_minute_rechecks.{index}.expect")
        command_names.append(command)
    missing = [
        command for command in REQUIRED_LAST_MINUTE_COMMANDS if command not in command_names
    ]
    require(not missing, f"last_minute_rechecks.missing:{missing}")

    manual = require_string_list(record.get("manual_rechecks"), "manual_rechecks")
    missing_manual = [
        check for check in REQUIRED_MANUAL_RECHECKS if check not in manual
    ]
    require(not missing_manual, f"manual_rechecks.missing:{missing_manual}")
    return {
        "tag_commands": commands,
        "last_minute_rechecks": command_names,
        "manual_rechecks": manual,
    }


def check_publication_effects(record: dict[str, Any]) -> dict[str, bool]:
    """Validate that the packet has not recorded publication effects."""

    effects = record.get("publication_effects")
    require(isinstance(effects, dict), "publication_effects.type")
    require(effects.get("tag_name") == INTENDED_TAG, "publication_effects.tag_name")
    require(effects.get("created_tag") is False, "publication_effects.created_tag")
    require(effects.get("pushed_tag") is False, "publication_effects.pushed_tag")
    return {
        "created_tag": effects.get("created_tag"),
        "pushed_tag": effects.get("pushed_tag"),
    }


def check_non_claims(record: dict[str, Any]) -> list[str]:
    """Validate packet non-claims and next required effect."""

    non_claims = require_string_list(record.get("non_claims"), "non_claims")
    required = [
        "This packet is not maintainer approval.",
        "This packet does not create a source-control tag.",
        "This packet does not push a source-control tag.",
    ]
    missing = [claim for claim in required if claim not in non_claims]
    require(not missing, f"non_claims.missing:{missing}")
    require(
        record.get("next_required_effect")
        == "Explicit maintainer approval is required before creating or pushing v0.1.0.",
        "next_required_effect",
    )
    return non_claims


def check_roll_forward_rule(record: dict[str, Any]) -> dict[str, str]:
    """Validate rollback and roll-forward instructions."""

    rule = record.get("rollback_roll_forward_rule")
    require(isinstance(rule, dict), "rollback_roll_forward_rule.type")
    local = require_string(
        rule.get("local_tag_created_not_pushed"),
        "rollback_roll_forward_rule.local",
    )
    pushed = require_string(rule.get("tag_pushed"), "rollback_roll_forward_rule.pushed")
    require("git tag -d v0.1.0" in local, "rollback_roll_forward_rule.local.delete")
    require("Do not retarget or delete the pushed tag" in pushed, "rollback_rule.pushed")
    require("explicit maintainer decision record" in pushed, "rollback_rule.decision")
    return {
        "local_tag_created_not_pushed": local,
        "tag_pushed": pushed,
    }


def check_packet(*, root: Path | None = None) -> dict[str, Any]:
    """Validate the tag approval packet and return evidence."""

    repo = root or repo_root()
    record = load_json(repo, PACKET_RECORD)
    require(record.get("schema_version") == "0.1", "schema_version")
    require(record.get("record_type") == "tag_approval_packet", "record_type")
    require(record.get("packet_id") == PACKET_ID, "packet_id")
    require(record.get("package_version") == PACKAGE_VERSION, "package_version")
    require(record.get("intended_tag") == INTENDED_TAG, "intended_tag")

    return {
        "checks": {
            "approval": check_approval(record),
            "commands": check_commands(record),
            "non_claims": check_non_claims(record),
            "publication_effects": check_publication_effects(record),
            "release_commit_requirement": check_release_commit_requirement(record, repo),
            "requested_effect": check_requested_effect(record, repo),
            "rollback_roll_forward_rule": check_roll_forward_rule(record),
        },
        "tag_approval_packet": PACKET_ID,
        "status": "passed",
    }


def main() -> int:
    """CLI entry point."""

    try:
        result = check_packet()
    except AssertionError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "tag_approval_packet": PACKET_ID,
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
