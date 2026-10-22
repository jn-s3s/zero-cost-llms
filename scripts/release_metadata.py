"""Validate a changelog and static version declaration without executing project code.

Run with --repo, --version-file and --version-key. Ready mode rejects existing or
older stable release versions; build mode checks the tag and checked-out commit.
Inspect mode only validates the metadata. Writes structured JSON and exits
nonzero on argument, validation, file or Git failures.
"""

import argparse
import ast
import json
import logging
import re
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path

LOGGER = logging.getLogger("release_metadata")
STABLE_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
SECTION = re.compile(r"^## \[([^\]]+)\](.*)$", re.MULTILINE)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """Convert a CLI argument error to ValueError for structured failure output."""
        raise ValueError(message)


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Return numeric stable-version parts; raise ValueError for other schemes."""
    if STABLE_VERSION.fullmatch(version) is None:
        raise ValueError(
            f"Expected a stable x.y.z version without leading zeroes, got {version!r}. "
            "Use the project's native validator for prereleases or other schemes."
        )
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def _read_project_file(root: Path, relative_path: str) -> tuple[Path, str]:
    """Read a file within root; reject environment files and escaping symlinks."""
    candidate = root / relative_path
    for part in candidate.parts:
        if part.casefold() == ".env" or part.casefold().startswith(".env."):
            raise ValueError("Environment files cannot be used as release metadata.")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"Release metadata path must stay within the repo: {relative_path}"
        )
    if resolved.name.casefold() == ".env" or resolved.name.casefold().startswith(
        ".env."
    ):
        raise ValueError("Environment files cannot be used as release metadata.")
    return resolved, resolved.read_text(encoding="utf-8-sig")


def _declared_version(path: Path, content: str, key: str) -> str:
    """Read a literal Python, JSON or TOML version; raise on unsupported forms."""
    if path.suffix == ".py":
        values = []
        for node in ast.parse(content, filename=str(path)).body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if any(
                isinstance(target, ast.Name) and target.id == key for target in targets
            ):
                if not isinstance(node.value, ast.Constant):
                    raise ValueError(
                        f"{key} must be a literal string; use a native resolver."
                    )
                values.append(node.value.value)
        if len(values) != 1:
            raise ValueError(
                f"Expected one top-level assignment for {key} in {path.name}."
            )
        value = values[0]
    else:
        if path.suffix == ".json":
            value = json.loads(content)
        elif path.suffix == ".toml":
            value = tomllib.loads(content)
        else:
            raise ValueError("Version files must be Python, JSON or TOML.")
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                raise ValueError(f"Version key {key!r} is missing from {path.name}.")
            value = value[part]
    if not isinstance(value, str):
        raise TypeError(f"Version key {key!r} must contain a string.")
    _version_tuple(value)
    return value


def _release_section(content: str) -> tuple[str, str, str | None]:
    """Read the newest release; require empty Unreleased and descending versions."""
    sections = list(SECTION.finditer(content))
    if len(sections) < 2 or sections[0].group(1) != "Unreleased":
        raise ValueError(
            "Put ## [Unreleased] above at least one dated release section."
        )
    if sections[0].group(2).strip():
        raise ValueError("Use the exact heading ## [Unreleased].")
    if content[sections[0].end() : sections[1].start()].strip():
        raise ValueError("## [Unreleased] must be empty before releasing.")
    versions = []
    for section in sections[1:]:
        version = section.group(1)
        version_parts = _version_tuple(version)
        suffix = section.group(2).strip()
        if not re.fullmatch(r"- \d{4}-\d{2}-\d{2}", suffix):
            raise ValueError(f"Release {version} needs a - YYYY-MM-DD date.")
        date.fromisoformat(suffix[2:])
        if versions and version_parts >= _version_tuple(versions[-1]):
            raise ValueError("Dated releases must have unique versions, newest first.")
        versions.append(version)
    end = sections[2].start() if len(sections) > 2 else len(content)
    notes = content[sections[1].end() : end]
    notes = re.split(r"(?m)^\[[^\]]+\]:", notes, maxsplit=1)[0].strip()
    visible_notes = re.sub(r"<!--.*?(?:-->|$)", "", notes, flags=re.DOTALL)
    meaningful_lines = [
        line
        for line in visible_notes.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not meaningful_lines:
        raise ValueError(f"Release {versions[0]} has no changelog entries.")
    previous_version = versions[1] if len(versions) > 1 else None
    return versions[0], notes, previous_version


def _git(root: Path, *arguments: str) -> str:
    """Run a metadata-only Git command; raise with command context on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError(
            f"Git {' '.join(arguments)} failed: {error.stderr.strip()}"
        ) from error
    return result.stdout.strip()


def _validate(arguments: argparse.Namespace) -> dict[str, object]:
    """Validate local inputs; callers must refresh Git tags before ready mode."""
    root = Path(arguments.repo).resolve(strict=True)
    _, changelog = _read_project_file(root, arguments.changelog)
    version_file, declaration = _read_project_file(root, arguments.version_file)
    version, notes, previous_version = _release_section(changelog)
    declared = _declared_version(version_file, declaration, arguments.version_key)
    if declared != version:
        raise ValueError(
            f"Changelog version {version} differs from declared {declared}."
        )
    if version_file.name == "package.json" and arguments.version_key == "version":
        lockfile, lock_content = _read_project_file(
            root, str(version_file.with_name("package-lock.json").relative_to(root))
        )
        # The empty key in packages..version identifies npm's root package.
        for key in ("version", "packages..version"):
            locked = _declared_version(lockfile, lock_content, key)
            if locked != declared:
                raise ValueError(
                    f"Lockfile {key} version {locked} differs from declared {declared}."
                )
    tag = f"v{version}"
    stable_tags = [
        item
        for item in _git(root, "tag", "--list", "v*").splitlines()
        if STABLE_VERSION.fullmatch(item[1:])
    ]
    if arguments.mode == "ready":
        if tag in stable_tags:
            raise ValueError(
                f"Tag {tag} already exists; prepare a new release version."
            )
        if stable_tags:
            latest = max(stable_tags, key=lambda item: _version_tuple(item[1:]))
            if _version_tuple(version) <= _version_tuple(latest[1:]):
                raise ValueError(f"Version {version} must be newer than {latest}.")
    elif arguments.mode == "build":
        if arguments.tag != tag:
            raise ValueError(f"Expected tag {tag}, got {arguments.tag!r}.")
        tag_commit = _git(root, "rev-parse", "--verify", f"{tag}^{{commit}}")
        if tag_commit != _git(root, "rev-parse", "HEAD"):
            raise ValueError(f"Checkout HEAD must be the commit tagged {tag}.")
    return {
        "version": version,
        "tag": tag,
        "previous_tag": f"v{previous_version}" if previous_version else None,
        "notes": notes,
    }


def main() -> int:
    """Parse CLI options and emit JSON; return 0 on success or 1 on input failures."""
    parser = _ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--version-file", required=True)
    parser.add_argument("--version-key", required=True)
    parser.add_argument(
        "--mode", choices=("inspect", "ready", "build"), default="ready"
    )
    parser.add_argument("--tag")
    arguments = None
    try:
        arguments = parser.parse_args()
        data = _validate(arguments)
    except (
        OSError,
        TypeError,
        ValueError,
        SyntaxError,
        subprocess.SubprocessError,
    ) as error:
        LOGGER.exception(
            "Release validation failed in mode %s",
            getattr(arguments, "mode", "arguments"),
        )
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(json.dumps({"success": True, "data": data}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
