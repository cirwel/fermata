"""Check the final no-effect preflight for publishing the local-alpha tag."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PREFLIGHT_ID = "local-alpha-v0.1.0-tag-publication-preflight"
RELEASE_TAG = "v0.1.0"
TAG_COMMANDS = [
    'git tag -a v0.1.0 -m "Fermata local alpha v0.1.0"',
    "git push origin v0.1.0",
]
INVALID_APPROVAL_REFERENCES = {
    "",
    "<approval-reference>",
    "approval-reference",
    "not_granted",
    "pending",
}


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


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


def local_tag_exists(root: Path) -> bool:
    """Return whether the release tag exists locally."""

    return bool(git_output(root, ["tag", "--list", RELEASE_TAG]))


def local_tag_target(root: Path) -> str:
    """Return the commit targeted by the local release tag."""

    return git_output(root, ["rev-parse", f"{RELEASE_TAG}^{{commit}}"])


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


def remote_tag_exists(root: Path) -> bool:
    """Return whether the release tag exists on the origin remote."""

    result = subprocess.run(
        [
            "git",
            "ls-remote",
            "--exit-code",
            "--tags",
            "origin",
            f"refs/tags/{RELEASE_TAG}",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 2:
        return False
    raise AssertionError(
        "remote_tag_check_failed:"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )


def parse_json_stdout(
    result: subprocess.CompletedProcess[str], *, label: str
) -> dict[str, Any]:
    """Parse a command's stdout as a JSON object with passed status."""

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"{label}.invalid_json:{exc}") from exc
    require(isinstance(data, dict), f"{label}.json_not_object")
    require(data.get("status") == "passed", f"{label}.status:{data.get('status')}")
    return data


def run_json_gate(root: Path, label: str, command: list[str]) -> dict[str, Any]:
    """Run a JSON-emitting validation gate and return a compact result."""

    result = parse_json_stdout(run_command(command, cwd=root), label=label)
    return {
        "command": command,
        "status": result.get("status"),
    }


def require_approval_reference(value: str | None) -> str:
    """Return a usable approval reference or fail before any expensive checks."""

    reference = (value or "").strip()
    require(reference not in INVALID_APPROVAL_REFERENCES, "approval_reference_required")
    require("<" not in reference and ">" not in reference, "approval_reference_placeholder")
    return reference


def source_preflight(root: Path, *, allow_current_branch: bool) -> dict[str, Any]:
    """Check source repository state before final publication commands."""

    head = git_output(root, ["rev-parse", "HEAD"])
    branch = git_output(root, ["branch", "--show-current"])
    origin_main = git_output(root, ["rev-parse", "--verify", "origin/main"])
    status = git_status(root)
    local_before = local_tag_exists(root)
    remote_before = remote_tag_exists(root)

    require(not status, f"source_status_dirty:{status}")
    require(not local_before, f"local_tag_exists:{RELEASE_TAG}")
    require(not remote_before, f"remote_tag_exists:{RELEASE_TAG}")
    if not allow_current_branch:
        require(branch == "main", f"source_branch:{branch}")
        require(head == origin_main, "source_head_not_origin_main")

    return {
        "allow_current_branch": allow_current_branch,
        "branch": branch,
        "head": head,
        "local_tag_exists_before": local_before,
        "origin_main": origin_main,
        "remote_tag_exists_before": remote_before,
        "status_clean": not status,
    }


def run_publication_preflight(
    *,
    root: Path | None = None,
    approval_reference: str | None,
    allow_current_branch: bool = False,
) -> dict[str, Any]:
    """Run final no-effect checks and return exact tag commands."""

    repo = root or repo_root()
    approval = require_approval_reference(approval_reference)
    source = source_preflight(repo, allow_current_branch=allow_current_branch)
    python = sys.executable
    release_candidate_command = [
        python,
        "scripts/check_local_alpha_release_candidate.py",
    ]
    if allow_current_branch:
        release_candidate_command.append("--allow-current-branch")

    gates = {
        "release_artifacts": run_json_gate(
            repo,
            "release_artifacts",
            [python, "scripts/check_local_alpha_release_artifacts.py"],
        ),
        "release_candidate": run_json_gate(
            repo,
            "release_candidate",
            release_candidate_command,
        ),
        "release_candidate_record": run_json_gate(
            repo,
            "release_candidate_record",
            [python, "scripts/check_local_alpha_release_candidate_record.py"],
        ),
        "tag_approval_packet": run_json_gate(
            repo,
            "tag_approval_packet",
            [python, "scripts/check_local_alpha_tag_approval_packet.py"],
        ),
        "validator": run_json_gate(
            repo,
            "validator",
            [python, "scripts/validate_local_alpha.py"],
        ),
    }

    local_after = local_tag_exists(repo)
    remote_after = remote_tag_exists(repo)
    require(not local_after, f"local_tag_exists_after:{RELEASE_TAG}")
    require(not remote_after, f"remote_tag_exists_after:{RELEASE_TAG}")

    return {
        "approval_reference": approval,
        "checks": {
            "gates": gates,
            "source": {
                **source,
                "local_tag_exists_after": local_after,
                "remote_tag_exists_after": remote_after,
            },
        },
        "exact_commands_after_this_preflight": TAG_COMMANDS,
        "publication_effects": {
            "created_tag": False,
            "pushed_tag": False,
            "tag_name": RELEASE_TAG,
        },
        "status": "passed",
        "tag_publication_preflight": PREFLIGHT_ID,
    }


def run_refusal_self_test(*, root: Path | None = None) -> dict[str, Any]:
    """Verify the no-approval path before and after publication."""

    repo = root or repo_root()
    local_before = local_tag_exists(repo)
    if local_before:
        head = git_output(repo, ["rev-parse", "HEAD"])
        target = local_tag_target(repo)
        target_is_ancestor = git_succeeds(
            repo, ["merge-base", "--is-ancestor", target, head]
        )
        require(target_is_ancestor, "local_tag_target_not_ancestor")
        return {
            "checks": {
                "local_tag_exists": True,
                "local_tag_target_is_ancestor_of_head": True,
                "tag_target": target,
                "head": head,
                "post_publication_mode": True,
            },
            "publication_effects": {
                "created_tag": False,
                "pushed_tag": False,
                "tag_name": RELEASE_TAG,
            },
            "status": "passed",
            "tag_publication_preflight": PREFLIGHT_ID,
        }

    try:
        require_approval_reference(None)
    except AssertionError as exc:
        require(str(exc) == "approval_reference_required", "missing_approval_reason")
    else:
        raise AssertionError("missing_approval_was_allowed")
    local_after = local_tag_exists(repo)
    require(local_before == local_after, "local_tag_state_changed")
    require(not local_after, f"local_tag_exists_after:{RELEASE_TAG}")
    return {
        "checks": {
            "missing_approval_rejected": True,
            "local_tag_exists_after": local_after,
            "local_tag_exists_before": local_before,
        },
        "publication_effects": {
            "created_tag": False,
            "pushed_tag": False,
            "tag_name": RELEASE_TAG,
        },
        "status": "passed",
        "tag_publication_preflight": PREFLIGHT_ID,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approval-reference",
        help=(
            "Required for final publication preflight. This script still does "
            "not create or push a tag."
        ),
    )
    parser.add_argument(
        "--allow-current-branch",
        action="store_true",
        help=(
            "Allow final preflight from the current clean branch instead of "
            "strict release mode on main at origin/main."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = parse_args(argv or sys.argv[1:])
    try:
        if args.approval_reference:
            result = run_publication_preflight(
                approval_reference=args.approval_reference,
                allow_current_branch=args.allow_current_branch,
            )
        else:
            result = run_refusal_self_test()
    except AssertionError as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "status": "failed",
                    "tag_publication_preflight": PREFLIGHT_ID,
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
