"""Run a local-alpha release-candidate dry run from a clean Git worktree."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any


RELEASE_ARTIFACT_COMMAND = [
    sys.executable,
    "scripts/check_local_alpha_release_artifacts.py",
]
VALIDATOR_COMMAND = [sys.executable, "scripts/validate_local_alpha.py"]


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def pyproject_version(root: Path) -> str:
    """Return the package version declared in pyproject.toml."""

    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str):
        raise AssertionError("pyproject.version")
    return version


def require(condition: bool, label: str) -> None:
    """Raise an assertion with a stable label when a check fails."""

    if not condition:
        raise AssertionError(label)


def run_command(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a command and raise with useful tails on failure."""

    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            "command_failed:"
            f"{command}\nstdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
        )
    return result


def git_output(root: Path, args: list[str]) -> str:
    """Return trimmed stdout from a Git command."""

    return run_command(["git", *args], cwd=root).stdout.strip()


def git_status(root: Path) -> str:
    """Return porcelain status including untracked files."""

    return git_output(root, ["status", "--porcelain", "--untracked-files=all"])


def tag_exists(root: Path, tag: str) -> bool:
    """Return whether the release tag exists in the current repository."""

    return bool(git_output(root, ["tag", "--list", tag]))


def parse_json_stdout(result: subprocess.CompletedProcess[str], *, label: str) -> dict[str, Any]:
    """Parse a command's stdout as a JSON object."""

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label}.invalid_json:{exc}") from exc
    require(isinstance(data, dict), f"{label}.json_not_object")
    require(data.get("status") == "passed", f"{label}.status:{data.get('status')}")
    return data


def source_preflight(
    root: Path, *, allow_current_branch: bool, tag: str
) -> dict[str, Any]:
    """Check source repository state before creating the candidate worktree."""

    head = git_output(root, ["rev-parse", "HEAD"])
    branch = git_output(root, ["branch", "--show-current"])
    origin_main = git_output(root, ["rev-parse", "--verify", "origin/main"])
    status = git_status(root)
    source_tag_exists = tag_exists(root, tag)

    require(not status, f"source_status_dirty:{status}")
    require(not source_tag_exists, f"source_tag_exists:{tag}")
    if not allow_current_branch:
        require(branch == "main", f"source_branch:{branch}")
        require(head == origin_main, "source_head_not_origin_main")

    return {
        "allow_current_branch": allow_current_branch,
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "release_tag_exists_before": source_tag_exists,
        "status_clean": not status,
    }


def add_detached_worktree(root: Path, candidate: Path, ref: str) -> None:
    """Create a detached Git worktree for the release-candidate dry run."""

    run_command(["git", "worktree", "add", "--detach", str(candidate), ref], cwd=root)


def remove_worktree(root: Path, candidate: Path) -> None:
    """Remove a temporary Git worktree."""

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(candidate)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def run_candidate_worktree(candidate: Path, *, tag: str) -> dict[str, Any]:
    """Run release checks inside a detached candidate worktree."""

    head = git_output(candidate, ["rev-parse", "HEAD"])
    status_before = git_status(candidate)
    tag_before = tag_exists(candidate, tag)
    require(not status_before, f"candidate_status_dirty_before:{status_before}")
    require(not tag_before, f"candidate_tag_exists_before:{tag}")

    release_artifacts = parse_json_stdout(
        run_command(RELEASE_ARTIFACT_COMMAND, cwd=candidate),
        label="release_artifacts",
    )
    validator = parse_json_stdout(
        run_command(VALIDATOR_COMMAND, cwd=candidate),
        label="validator",
    )

    status_after = git_status(candidate)
    tag_after = tag_exists(candidate, tag)
    require(not status_after, f"candidate_status_dirty_after:{status_after}")
    require(not tag_after, f"candidate_tag_exists_after:{tag}")

    return {
        "head": head,
        "release_artifacts": {
            "release_artifacts": release_artifacts.get("release_artifacts"),
            "status": release_artifacts.get("status"),
        },
        "release_tag_exists_after": tag_after,
        "release_tag_exists_before": tag_before,
        "status_clean_after": not status_after,
        "status_clean_before": not status_before,
        "validator": {
            "checked": validator.get("checked"),
            "passed": validator.get("passed"),
            "status": validator.get("status"),
        },
    }


def run_dry_run(*, root: Path | None = None, allow_current_branch: bool = False) -> dict[str, Any]:
    """Run the full release-candidate dry run and return JSON-safe evidence."""

    source_root = root or repo_root()
    version = pyproject_version(source_root)
    tag = f"v{version}"
    release_candidate = f"local-alpha-v{version}"
    source = source_preflight(
        source_root, allow_current_branch=allow_current_branch, tag=tag
    )
    with tempfile.TemporaryDirectory(prefix="fermata_release_candidate_") as tmp:
        candidate = Path(tmp) / "candidate"
        add_detached_worktree(source_root, candidate, source["head"])
        try:
            candidate_result = run_candidate_worktree(candidate, tag=tag)
        finally:
            remove_worktree(source_root, candidate)

    source_tag_after = tag_exists(source_root, tag)
    require(not source_tag_after, f"source_tag_exists_after:{tag}")
    return {
        "checks": {
            "candidate_worktree": candidate_result,
            "source": {
                **source,
                "release_tag_exists_after": source_tag_after,
            },
        },
        "release_candidate": release_candidate,
        "status": "passed",
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-current-branch",
        action="store_true",
        help=(
            "Allow running the dry run from the current clean branch instead of "
            "strict release mode on main at origin/main."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = parse_args(argv or sys.argv[1:])
    try:
        result = run_dry_run(allow_current_branch=args.allow_current_branch)
    except AssertionError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "release_candidate": "local-alpha",
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
