"""Check the local-alpha release-candidate evidence record.

Version-aware: the release version is read from ``pyproject.toml`` and the
record path, candidate id, intended tag, and release-artifacts id are derived
from it.

Two record states are accepted:

``pending_ci``
    A pre-merge candidate. The eventual release commit is not yet on ``main``,
    so it has no green CI evidence. The record names the candidate branch, the
    placeholder commit, and the exact requirements to fill before it can become
    a ``pre_tag_candidate``. This keeps a fresh version bump honestly green:
    the record claims no commit/CI evidence it cannot yet have.

``pre_tag_candidate``
    A post-merge candidate. The record names a real merged-``main`` commit that
    is an ancestor of ``HEAD``, at least two green ``ci / golden`` run URLs for
    that commit, and a strict release-candidate dry-run snapshot. The recorded
    validator gates must equal the live validator gate set.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


PENDING_COMMIT_PLACEHOLDER = "<fill-with-merged-main-commit-after-ci>"
PENDING_DRY_RUN_COMMAND = (
    "python3 scripts/check_local_alpha_release_candidate.py --allow-current-branch"
)
STRICT_DRY_RUN_COMMAND = "python3 scripts/check_local_alpha_release_candidate.py"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_NON_CLAIMS = [
    "No source-control tag has been created.",
    "No source-control tag has been pushed.",
    "This record is pre-tag evidence, not publication approval.",
]


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def pyproject_version(root: Path) -> str:
    """Return the package version declared in pyproject.toml."""

    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    require(isinstance(version, str), "pyproject.version")
    return version


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
    """Return a non-empty string value or fail."""

    require(isinstance(value, str) and bool(value), label)
    return value


def require_string_list(value: Any, label: str) -> list[str]:
    """Return a non-empty list of non-empty strings or fail."""

    require(isinstance(value, list) and bool(value), f"{label}.type")
    items: list[str] = []
    for index, item in enumerate(value):
        require(isinstance(item, str) and bool(item), f"{label}.{index}")
        items.append(item)
    return items


def live_gate_names(root: Path) -> list[str]:
    """Return the current validator gate names from the source tree."""

    sys.path.insert(0, str(root / "src"))
    from fermata.local_alpha_validator import gates

    return [gate.name for gate in gates()]


def check_publication_effects(record: dict[str, Any], tag: str) -> dict[str, bool]:
    """Validate that the record remains pre-tag evidence."""

    effects = record.get("publication_effects")
    require(isinstance(effects, dict), "publication_effects.type")
    require(effects.get("tag_name") == tag, "publication_effects.tag_name")
    require(effects.get("created_tag") is False, "publication_effects.created_tag")
    require(effects.get("pushed_tag") is False, "publication_effects.pushed_tag")
    return {
        "created_tag": effects.get("created_tag"),
        "pushed_tag": effects.get("pushed_tag"),
    }


def check_non_claims(record: dict[str, Any]) -> list[str]:
    """Validate the required pre-tag non-claims."""

    non_claims = record.get("non_claims")
    require(isinstance(non_claims, list), "non_claims.type")
    for phrase in REQUIRED_NON_CLAIMS:
        require(phrase in non_claims, f"non_claims.missing:{phrase}")
    return non_claims


def check_pending(record: dict[str, Any], *, tag: str) -> dict[str, Any]:
    """Validate a pre-merge ``pending_ci`` candidate record."""

    candidate_commit = require_string(
        record.get("candidate_commit"), "candidate_commit"
    )
    require(
        candidate_commit == PENDING_COMMIT_PLACEHOLDER,
        "candidate_commit.pending_placeholder",
    )
    candidate_branch = require_string(
        record.get("candidate_branch"), "candidate_branch"
    )

    pending = record.get("pending_ci")
    require(isinstance(pending, dict), "pending_ci.type")
    require(pending.get("ci_status") == "pending", "pending_ci.ci_status")
    require(
        pending.get("dry_run_command") == PENDING_DRY_RUN_COMMAND,
        "pending_ci.dry_run_command",
    )
    required_before = require_string_list(
        pending.get("required_before_pre_tag"), "pending_ci.required_before_pre_tag"
    )

    ci_evidence = record.get("ci_evidence")
    require(ci_evidence == [], "pending_ci.ci_evidence_must_be_empty")

    return {
        "candidate_branch": candidate_branch,
        "candidate_commit": candidate_commit,
        "ci_status": "pending",
        "required_before_pre_tag": required_before,
    }


def check_ci_evidence(record: dict[str, Any]) -> list[dict[str, str]]:
    """Validate CI evidence rows for a post-merge candidate."""

    rows = record.get("ci_evidence")
    require(isinstance(rows, list) and len(rows) >= 2, "ci_evidence.count")
    checked: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        require(isinstance(row, dict), f"ci_evidence.{index}.type")
        require(row.get("workflow") == "ci", f"ci_evidence.{index}.workflow")
        require(row.get("check") == "golden", f"ci_evidence.{index}.check")
        require(row.get("conclusion") == "SUCCESS", f"ci_evidence.{index}.conclusion")
        url = require_string(row.get("url"), f"ci_evidence.{index}.url")
        require(
            url.startswith("https://github.com/cirwel/fermata/actions/runs/"),
            f"ci_evidence.{index}.url_prefix",
        )
        checked.append(
            {
                "completed_at": require_string(
                    row.get("completed_at"), f"ci_evidence.{index}.completed_at"
                ),
                "url": url,
            }
        )
    return checked


def check_dry_run(
    record: dict[str, Any],
    candidate_commit: str,
    *,
    gate_names: list[str],
    release_artifacts: str,
) -> dict[str, Any]:
    """Validate the strict release-candidate dry-run snapshot."""

    dry_run = record.get("dry_run_evidence")
    require(isinstance(dry_run, dict), "dry_run.type")
    require(dry_run.get("command") == STRICT_DRY_RUN_COMMAND, "dry_run.command")
    require(dry_run.get("status") == "passed", "dry_run.status")

    source = dry_run.get("source")
    require(isinstance(source, dict), "dry_run.source.type")
    require(source.get("allow_current_branch") is False, "dry_run.source.strict_mode")
    require(source.get("branch") == "main", "dry_run.source.branch")
    require(source.get("head") == candidate_commit, "dry_run.source.head")
    require(source.get("origin_main") == candidate_commit, "dry_run.source.origin_main")
    require(source.get("status_clean") is True, "dry_run.source.status_clean")
    require(source.get("release_tag_exists_before") is False, "dry_run.source.tag_before")
    require(source.get("release_tag_exists_after") is False, "dry_run.source.tag_after")

    worktree = dry_run.get("candidate_worktree")
    require(isinstance(worktree, dict), "dry_run.worktree.type")
    require(worktree.get("head") == candidate_commit, "dry_run.worktree.head")
    require(worktree.get("status_clean_before") is True, "dry_run.worktree.clean_before")
    require(worktree.get("status_clean_after") is True, "dry_run.worktree.clean_after")
    require(
        worktree.get("release_tag_exists_before") is False,
        "dry_run.worktree.tag_before",
    )
    require(
        worktree.get("release_tag_exists_after") is False,
        "dry_run.worktree.tag_after",
    )

    artifacts = worktree.get("release_artifacts")
    require(isinstance(artifacts, dict), "dry_run.release_artifacts.type")
    require(
        artifacts.get("release_artifacts") == release_artifacts,
        "dry_run.release_artifacts.id",
    )
    require(artifacts.get("status") == "passed", "dry_run.release_artifacts.status")

    validator = worktree.get("validator")
    require(isinstance(validator, dict), "dry_run.validator.type")
    require(validator.get("status") == "passed", "dry_run.validator.status")
    require(validator.get("checked") == gate_names, "dry_run.validator.checked")
    require(validator.get("passed") == gate_names, "dry_run.validator.passed")
    return {
        "recorded_gates": gate_names,
        "release_artifacts": artifacts.get("release_artifacts"),
        "status": dry_run.get("status"),
    }


def check_pre_tag(
    record: dict[str, Any],
    repo: Path,
    *,
    gate_names: list[str],
    release_artifacts: str,
) -> dict[str, Any]:
    """Validate a post-merge ``pre_tag_candidate`` record."""

    candidate_commit = require_string(
        record.get("candidate_commit"), "candidate_commit"
    )
    require(COMMIT_RE.match(candidate_commit) is not None, "candidate_commit.format")
    candidate_commit_available = git_succeeds(
        repo, ["cat-file", "-e", f"{candidate_commit}^{{commit}}"]
    )
    candidate_commit_is_ancestor = None
    if candidate_commit_available:
        candidate_commit_is_ancestor = git_succeeds(
            repo, ["merge-base", "--is-ancestor", candidate_commit, "HEAD"]
        )
        require(candidate_commit_is_ancestor, "candidate_commit.ancestor")

    source = record.get("candidate_commit_source")
    require(isinstance(source, dict), "candidate_commit_source.type")
    require_string(source.get("pull_request"), "candidate_commit_source.pull_request")
    require_string(source.get("merged_at"), "candidate_commit_source.merged_at")

    return {
        "candidate_commit": {
            "available_in_checkout": candidate_commit_available,
            "is_ancestor_of_head": candidate_commit_is_ancestor,
            "sha": candidate_commit,
        },
        "ci_evidence": check_ci_evidence(record),
        "dry_run": check_dry_run(
            record,
            candidate_commit,
            gate_names=gate_names,
            release_artifacts=release_artifacts,
        ),
    }


def check_record(*, root: Path | None = None) -> dict[str, Any]:
    """Validate the release-candidate record and return evidence."""

    repo = root or repo_root()
    version = pyproject_version(repo)
    tag = f"v{version}"
    candidate_id = f"local-alpha-v{version}-rc1"
    candidate_record = Path(
        f"references/release-candidates-v0/local-alpha-v{version}-rc1.json"
    )
    release_artifacts = f"local-alpha-v{version}"

    record = load_json(repo, candidate_record)
    require(record.get("schema_version") == "0.1", "schema_version")
    require(record.get("record_type") == "release_candidate", "record_type")
    require(record.get("candidate_id") == candidate_id, "candidate_id")
    require(record.get("package_version") == version, "package_version")
    require(record.get("intended_tag") == tag, "intended_tag")

    status = record.get("status")
    require(status in {"pending_ci", "pre_tag_candidate"}, f"status:{status}")
    check_publication_effects(record, tag)
    check_non_claims(record)

    if status == "pending_ci":
        state_checks = check_pending(record, tag=tag)
    else:
        gate_names = live_gate_names(repo)
        state_checks = check_pre_tag(
            record,
            repo,
            gate_names=gate_names,
            release_artifacts=release_artifacts,
        )

    return {
        "checks": {
            "publication_effects": {"created_tag": False, "pushed_tag": False},
            "state": status,
            **state_checks,
        },
        "release_candidate_record": candidate_id,
        "status": "passed",
    }


def main() -> int:
    """CLI entry point."""

    try:
        result = check_record()
    except AssertionError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "release_candidate_record": "local-alpha",
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
