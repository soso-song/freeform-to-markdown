#!/usr/bin/env python3
"""Fail when release inputs contain machine-local paths or likely live secrets.

This is intentionally conservative. Test fixtures may contain explicit values prefixed
with ``EXAMPLE_`` or use RFC-reserved domains and documentation addresses.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TEXT_SUFFIXES = {
    ".cfg",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {".git", ".venv", "dist", "build", "__pycache__"}
RULES = {
    "absolute home path": re.compile(r"(?:/Users/|/home/)[^\s'\"<>]+"),  # privacy-scan: allow
    "GitHub token": re.compile(r"\b(?:gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private board store": re.compile(  # privacy-scan: allow
        r"group\.com\.apple\.freeform/Boards/(?:boards\.db|Assets)"  # privacy-scan: allow
    ),
}


def tracked_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.is_file()]
    return [root / line for line in output.splitlines() if line]


def scan(root: Path) -> list[tuple[str, Path, int]]:
    findings: list[tuple[str, Path, int]] = []
    for path in tracked_files(root):
        if any(part in SKIP_PARTS for part in path.parts) or path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            if "privacy-scan: allow" in line or "EXAMPLE_" in line:
                continue
            for label, pattern in RULES.items():
                if pattern.search(line):
                    findings.append((label, path.relative_to(root), number))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    findings = scan(root)
    for label, path, line in findings:
        print(f"{path}:{line}: {label}", file=sys.stderr)
    if findings:
        print(f"privacy scan failed with {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("privacy scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
