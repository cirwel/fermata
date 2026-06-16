"""Check the local-alpha release-candidate evidence record."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


CANDIDATE_ID = "local-alpha-v0.1.0-rc1"
CANDIDATE_RECORD = Path("references/release-candidates-v0/local-alpha-v0.1.0-rc1.json")
PACKAGE_VERSION = "0.1.0"
INTENDED_TAG = "v0.1.0"
RELEASE_ARTIFACTS = "local-alpha-v0.1.0"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
RECORDED_DRY_RUN_GATES = [
    "compileall",
    "schema_json",
    "golden_json",
    "golden_checks",
    "cli_smoke",
    "run_bundle_contract",
    "runtime_api",
    "local_service",
    "recovery_evidence",
    "recovery_evidence_example",
    "release_artifacts",
    "package_build",
    "diff_check",
]


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def require(condition: bool, label: str) -> None:
    """Raise an assertion with a stable label when a check fails."""

    if not condition:
        raise AssertionError(label)


def load_json(root: Path, path: Path) -> dict[str, Any]:
    """Load a JSON object from a repo-relative path."""

    data = json.loads((root / path).read_text(encoding="utf-8"))
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


def check_ci_evidence(record: dict[str, Any]) -> list[dict[str, str]]:
    """Validate CI evidence rows."""

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


def check_dry_run(record: dict[str, Any], candidate_commit: str) -> dict[str, Any]:
    """Validate dry-run evidence."""

    dry_run = record.get("dry_run_evidence")
    require(isinstance(dry_run, dict), "dry_run.type")
    require(
        dry_run.get("command") == "python3 scripts/check_local_alpha_release_candidate.py",
        "dry_run.command",
    )
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

    release_artifacts = worktree.get("release_artifacts")
    require(isinstance(release_artifacts, dict), "dry_run.release_artifacts.type")
    require(
        release_artifacts.get("release_artifacts") == RELEASE_ARTIFACTS,
        "dry_run.release_artifacts.id",
    )
    require(release_artifacts.get("status") == "passed", "dry_run.release_artifacts.status")

    validator = worktree.get("validator")
    require(isinstance(validator, dict), "dry_run.validator.type")
    require(validator.get("status") == "passed", "dry_run.validator.status")
    require(
        validator.get("checked") == RECORDED_DRY_RUN_GATES,
        "dry_run.validator.checked",
    )
    require(
        validator.get("passed") == RECORDED_DRY_RUN_GATES,
        "dry_run.validator.passed",
    )
    return {
        "recorded_gates": RECORDED_DRY_RUN_GATES,
        "release_artifacts": release_artifacts.get("release_artifacts"),
        "status": dry_run.get("status"),
    }


def check_publication_effects(record: dict[str, Any]) -> dict[str, bool]:
    """Validate that the record remains pre-tag evidence."""

    effects = record.get("publication_effects")
    require(isinstance(effects, dict), "publication_effects.type")
    require(effects.get("tag_name") == INTENDED_TAG, "publication_effects.tag_name")
    require(effects.get("created_tag") is False, "publication_effects.created_tag")
    require(effects.get("pushed_tag") is False, "publication_effects.pushed_tag")
    return {
        "created_tag": effects.get("created_tag"),
        "pushed_tag": effects.get("pushed_tag"),
    }


def check_record(*, root: Path | None = None) -> dict[str, Any]:
    """Validate the release-candidate record and return evidence."""

    repo = root or repo_root()
    record = load_json(repo, CANDIDATE_RECORD)
    require(record.get("schema_version") == "0.1", "schema_version")
    require(record.get("record_type") == "release_candidate", "record_type")
    require(record.get("candidate_id") == CANDIDATE_ID, "candidate_id")
    require(record.get("package_version") == PACKAGE_VERSION, "package_version")
    require(record.get("intended_tag") == INTENDED_TAG, "intended_tag")
    require(record.get("status") == "pre_tag_candidate", "status")

    candidate_commit = require_string(record.get("candidate_commit"), "candidate_commit")
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
    require(
        source.get("pull_request") == "https://github.com/cirwel/fermata/pull/27",
        "candidate_commit_source.pull_request",
    )
    require_string(source.get("merged_at"), "candidate_commit_source.merged_at")

    non_claims = record.get("non_claims")
    require(isinstance(non_claims, list), "non_claims.type")
    for phrase in [
        "No source-control tag has been created.",
        "No source-control tag has been pushed.",
        "This record is pre-tag evidence, not publication approval.",
    ]:
        require(phrase in non_claims, f"non_claims.missing:{phrase}")

    return {
        "checks": {
            "candidate_commit": {
                "available_in_checkout": candidate_commit_available,
                "is_ancestor_of_head": candidate_commit_is_ancestor,
                "sha": candidate_commit,
            },
            "ci_evidence": check_ci_evidence(record),
            "dry_run": check_dry_run(record, candidate_commit),
            "publication_effects": check_publication_effects(record),
        },
        "release_candidate_record": CANDIDATE_ID,
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
                    "release_candidate_record": CANDIDATE_ID,
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
