#!/usr/bin/env python3
"""Compute the next release tag and author-attributed release notes."""

from __future__ import annotations

import re
import subprocess
import sys

TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], text=True, encoding="utf-8"
    ).strip()


def release_version() -> tuple[str, str | None]:
    tags = git("tag", "--list").splitlines()
    current_tags = [
        match for tag in git("tag", "--points-at", "HEAD").splitlines()
        if (match := TAG_PATTERN.fullmatch(tag))
    ]
    if current_tags:
        match = max(current_tags, key=lambda item: tuple(map(int, item.groups())))
        version = ".".join(match.groups())
        return f"v{version}", f"v{version}"

    versions = [
        (tuple(map(int, match.groups())), tag)
        for tag in tags
        if (match := TAG_PATTERN.fullmatch(tag))
    ]
    if not versions:
        return "v1.0.0", None
    (major, minor, patch), previous_tag = max(versions)
    return f"v{major}.{minor}.{patch + 1}", previous_tag


def release_notes(previous_tag: str | None) -> str:
    version, _ = release_version()
    revision_range = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    entries = git(
        "log", "--reverse", "--format=%h%x09%an%x09%s", revision_range
    ).splitlines()
    if previous_tag:
        files = git("diff", "--name-only", f"{previous_tag}..HEAD").splitlines()
    else:
        files = sorted(set(git("log", "--format=", "--name-only", "HEAD").splitlines()))
        files = [path for path in files if path]

    lines = [f"# VoltForge {version}", "", "## Modifications"]
    if entries:
        for entry in entries:
            commit, author, subject = entry.split("\t", 2)
            lines.append(f"- {subject} — **{author}** (`{commit}`)")
    else:
        lines.append("- Aucun nouveau commit depuis la version précédente.")
    if files:
        lines.extend(["", "## Fichiers concernés"])
        lines.extend(f"- `{path}`" for path in files)
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"version", "notes"}:
        print("Usage: release_version.py {version|notes}", file=sys.stderr)
        return 2
    tag, previous_tag = release_version()
    if sys.argv[1] == "version":
        print(tag)
    else:
        print(release_notes(previous_tag), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
