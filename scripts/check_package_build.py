"""Check Fermata package build artifacts and console entry points."""

from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path
from typing import Any


def pyproject_version(root: Path) -> str:
    """Return the package version declared in pyproject.toml."""

    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    assert isinstance(version, str), "pyproject.version"
    return version


EXPECTED_CONSOLE_SCRIPTS = {
    "fermata",
    "fermata-golden-checks",
    "fermata-local-adapter-spike",
    "fermata-local-alpha-validate",
    "fermata-parse-tongue",
    "fermata-render-tongue",
}

EXPECTED_SDIST_FILES = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "docs/deployability-dossier-v0.md",
    "docs/local-alpha-release-checklist-v0.md",
    "docs/local-service-v0.md",
    "docs/recovery-evidence-v0.md",
    "docs/releases/local-alpha-v0.1.0-tag-checklist.md",
    "docs/releases/local-alpha-v0.1.0.md",
    "docs/releases/local-alpha-v0.1.1-tag-checklist.md",
    "docs/releases/local-alpha-v0.1.1.md",
    "docs/runtime-api-v0.md",
    "examples/local-alpha/file-scope.json",
    "references/recovery-evidence-examples-v0/local-service-run-packet-v0.json",
    "references/recovery-evidence-templates-v0/service-incident-report-template.json",
    "references/recovery-evidence-templates-v0/service-reconciliation-report-template.json",
    "references/release-approvals-v0/local-alpha-v0.1.0-tag-approval-packet.json",
    "references/release-approvals-v0/local-alpha-v0.1.1-tag-approval-packet.json",
    "references/release-candidates-v0/local-alpha-v0.1.0-rc1.json",
    "references/release-candidates-v0/local-alpha-v0.1.1-rc1.json",
    "references/governed-effect-ir-v0.schema.json",
    "references/tongue-golden-tests-v0.json",
    "scripts/check_local_alpha_release_candidate.py",
    "scripts/check_local_alpha_release_candidate_record.py",
    "scripts/check_local_alpha_tag_approval_packet.py",
    "scripts/check_local_alpha_tag_publication_preflight.py",
    "scripts/check_local_service.py",
    "scripts/check_local_alpha_release_artifacts.py",
    "scripts/check_package_build.py",
    "scripts/check_recovery_evidence.py",
    "scripts/check_recovery_evidence_example.py",
    "scripts/check_runtime_api.py",
    "scripts/validate_local_alpha.py",
    "src/fermata/runtime_api.py",
    "src/fermata/service_records.py",
    "src/fermata/service.py",
    "src/fermata/reference_data/governed-effect-ir-v0.schema.json",
    "src/fermata/reference_data/tongue-golden-tests-v0.json",
    "src/fermata/reference_data/ai-native-tongue-seed-corpus-v0.jsonl",
}

EXPECTED_WHEEL_DATA = {
    "fermata/reference_data/__init__.py",
    "fermata/reference_data/governed-effect-ir-v0.schema.json",
    "fermata/reference_data/tongue-golden-tests-v0.json",
    "fermata/reference_data/ai-native-tongue-seed-corpus-v0.jsonl",
}

REFERENCE_DATA_PAIRS = {
    "references/governed-effect-ir-v0.schema.json": (
        "src/fermata/reference_data/governed-effect-ir-v0.schema.json"
    ),
    "references/tongue-golden-tests-v0.json": (
        "src/fermata/reference_data/tongue-golden-tests-v0.json"
    ),
    "references/ai-native-tongue-seed-corpus-v0.jsonl": (
        "src/fermata/reference_data/ai-native-tongue-seed-corpus-v0.jsonl"
    ),
}


def repo_root() -> Path:
    """Return the source checkout root."""

    return Path(__file__).resolve().parents[1]


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and raise with useful tails on failure."""

    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stdout_tail = result.stdout[-4000:]
        stderr_tail = result.stderr[-4000:]
        raise AssertionError(
            f"command failed: {command}\nstdout:\n{stdout_tail}\nstderr:\n{stderr_tail}"
        )
    return result


def copy_clean_source(source: Path, destination: Path) -> None:
    """Copy the working tree while excluding generated build artifacts."""

    ignore = shutil.ignore_patterns(
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "build",
        "dist",
    )
    shutil.copytree(source, destination, ignore=ignore)


def build_artifacts(source: Path, out_dir: Path) -> tuple[Path, Path]:
    """Build wheel and sdist in an isolated source copy."""

    run_command(
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(out_dir)],
        cwd=source,
    )
    wheels = sorted(out_dir.glob("*.whl"))
    sdists = sorted(out_dir.glob("*.tar.gz"))
    assert len(wheels) == 1, wheels
    assert len(sdists) == 1, sdists
    return wheels[0], sdists[0]


def wheel_dist_info(names: set[str], suffix: str) -> str:
    """Return a single dist-info member ending with suffix."""

    matches = sorted(
        name for name in names if ".dist-info/" in name and name.endswith(suffix)
    )
    assert len(matches) == 1, matches
    return matches[0]


def read_wheel_entry_points(wheel: Path) -> set[str]:
    """Return console script names declared by the wheel."""

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points_name = wheel_dist_info(names, "entry_points.txt")
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(entry_points_name).decode("utf-8"))
    return set(parser["console_scripts"])


def check_wheel(wheel: Path, source: Path) -> dict[str, Any]:
    """Validate wheel metadata and package module contents."""

    expected_modules = {
        f"fermata/{path.relative_to(source / 'src/fermata').as_posix()}"
        for path in sorted((source / "src/fermata").rglob("*.py"))
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        metadata_name = wheel_dist_info(names, "METADATA")
        metadata = archive.read(metadata_name).decode("utf-8")
        package_modules = {
            name
            for name in names
            if name.startswith("fermata/") and name.endswith(".py")
        }

    missing_modules = sorted(expected_modules - package_modules)
    unexpected_modules = sorted(package_modules - expected_modules)
    assert not missing_modules, missing_modules
    assert not unexpected_modules, unexpected_modules
    missing_package_data = sorted(EXPECTED_WHEEL_DATA - names)
    assert not missing_package_data, missing_package_data
    version = pyproject_version(source)
    assert "Name: fermata-runtime" in metadata
    assert f"Version: {version}" in metadata

    entry_points = read_wheel_entry_points(wheel)
    missing_entry_points = sorted(EXPECTED_CONSOLE_SCRIPTS - entry_points)
    assert not missing_entry_points, missing_entry_points

    return {
        "entry_points": sorted(entry_points),
        "package_data": sorted(EXPECTED_WHEEL_DATA),
        "module_count": len(package_modules),
        "metadata": {"name": "fermata-runtime", "version": version},
    }


def sdist_members(sdist: Path) -> set[str]:
    """Return sdist members without the top-level archive prefix."""

    with tarfile.open(sdist, "r:gz") as archive:
        names = {member.name for member in archive.getmembers() if member.isfile()}
    prefixes = {name.split("/", 1)[0] for name in names}
    assert len(prefixes) == 1, prefixes
    prefix = next(iter(prefixes))
    return {name.removeprefix(prefix + "/") for name in names}


def check_sdist(sdist: Path) -> dict[str, Any]:
    """Validate source distribution review and validation files."""

    members = sdist_members(sdist)
    missing = sorted(EXPECTED_SDIST_FILES - members)
    assert not missing, missing
    assert not any("__pycache__" in member for member in members)
    assert not any(member.endswith((".pyc", ".pyo")) for member in members)
    return {
        "checked_files": sorted(EXPECTED_SDIST_FILES),
        "member_count": len(members),
    }


def check_reference_data_sync(source: Path) -> dict[str, Any]:
    """Verify packaged reference copies match the canonical source fixtures."""

    checked = []
    for canonical, packaged in REFERENCE_DATA_PAIRS.items():
        canonical_path = source / canonical
        packaged_path = source / packaged
        assert canonical_path.read_bytes() == packaged_path.read_bytes(), (
            canonical,
            packaged,
        )
        checked.append({"canonical": canonical, "packaged": packaged})
    return {"checked": checked}


def venv_paths(venv_dir: Path) -> tuple[Path, Path]:
    """Return python executable and scripts directory for a venv."""

    if os.name == "nt":
        scripts_dir = venv_dir / "Scripts"
        return scripts_dir / "python.exe", scripts_dir
    scripts_dir = venv_dir / "bin"
    return scripts_dir / "python", scripts_dir


def console_script_exists(scripts_dir: Path, name: str) -> bool:
    """Return true when a console script wrapper exists."""

    candidates = [scripts_dir / name]
    if os.name == "nt":
        candidates.extend([scripts_dir / f"{name}.exe", scripts_dir / f"{name}.cmd"])
    return any(candidate.exists() for candidate in candidates)


def check_installed_wheel(wheel: Path, venv_dir: Path) -> dict[str, Any]:
    """Install the wheel in a fresh venv and check entry point wrappers."""

    venv.EnvBuilder(with_pip=True, system_site_packages=True).create(venv_dir)
    python, scripts_dir = venv_paths(venv_dir)
    run_command([str(python), "-m", "pip", "install", "--no-index", str(wheel)])

    missing_scripts = [
        name
        for name in sorted(EXPECTED_CONSOLE_SCRIPTS)
        if not console_script_exists(scripts_dir, name)
    ]
    assert not missing_scripts, missing_scripts

    import_check = run_command(
        [
            str(python),
            "-c",
            (
                "from pathlib import Path; "
                f"venv_root = Path({str(venv_dir)!r}).resolve(); "
                "import fermata; "
                "assert Path(fermata.__file__).resolve().is_relative_to(venv_root); "
                "from fermata import CHORUS, RuntimeOutput, interpret, run; "
                "assert CHORUS.startswith('Agents may propose'); "
                "assert RuntimeOutput; assert interpret; assert run"
            ),
        ]
    )
    cli_help = run_command([str(scripts_dir / "fermata"), "--help"])
    parser_run = run_command(
        [
            str(scripts_dir / "fermata-parse-tongue"),
            'claim "package entry point works" evidence:[package_gate]',
        ]
    )
    outside_cwd = venv_dir.parent / "outside_cwd"
    outside_cwd.mkdir()
    golden_run = run_command(
        [str(scripts_dir / "fermata-golden-checks")],
        cwd=outside_cwd,
    )
    golden_result = json.loads(golden_run.stdout)

    return {
        "console_scripts_present": sorted(EXPECTED_CONSOLE_SCRIPTS),
        "import_check_returncode": import_check.returncode,
        "fermata_help_contains": "Evaluate local governed-effect JSON records."
        in cli_help.stdout,
        "golden_checks_status": golden_result["status"],
        "golden_checks_used_packaged_references": not (outside_cwd / "references").exists(),
        "parse_tongue_contains": "package entry point works" in parser_run.stdout,
    }


def main() -> int:
    """Run package build checks and print machine-readable evidence."""

    root = repo_root()
    with tempfile.TemporaryDirectory(prefix="fermata_package_gate_") as tmp:
        tmp_root = Path(tmp)
        source_copy = tmp_root / "source"
        out_dir = tmp_root / "dist"
        venv_dir = tmp_root / "venv"
        copy_clean_source(root, source_copy)
        wheel, sdist = build_artifacts(source_copy, out_dir)
        wheel_result = check_wheel(wheel, source_copy)
        sdist_result = check_sdist(sdist)
        reference_data_result = check_reference_data_sync(source_copy)
        install_result = check_installed_wheel(wheel, venv_dir)

    print(
        json.dumps(
            {
                "artifacts": {
                    "sdist": sdist.name,
                    "wheel": wheel.name,
                },
                "checks": {
                    "installed_wheel": install_result,
                    "reference_data": reference_data_result,
                    "sdist": sdist_result,
                    "wheel": wheel_result,
                },
                "status": "passed",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
