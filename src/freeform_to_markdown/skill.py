"""Install the bundled agent workflow without maintaining divergent copies."""

from __future__ import annotations

import importlib.resources
import os
import shutil
from pathlib import Path


def bundled_skill() -> Path:
    packaged = importlib.resources.files("freeform_to_markdown").joinpath("bundled_skill")
    candidate = Path(str(packaged))
    if candidate.is_dir():
        return candidate
    source_candidate = Path(__file__).resolve().parents[2] / "skills" / "freeform-to-markdown"
    if source_candidate.is_dir():
        return source_candidate
    raise FileNotFoundError("bundled freeform-to-markdown Skill is unavailable")


def install_skill(target: str) -> list[Path]:
    if target not in {"codex", "claude", "both"}:
        raise ValueError("target must be codex, claude, or both")
    codex = (
        Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        / "skills"
        / "freeform-to-markdown"
    )
    claude = Path.home() / ".claude" / "skills" / "freeform-to-markdown"
    destinations = [codex] if target == "codex" else [claude]
    if target == "both":
        destinations = [codex, claude]
    for destination in destinations:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Skill destination already exists: {destination}")
    source = bundled_skill()
    primary = destinations[0]
    primary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, primary)
    installed = [primary]
    if len(destinations) == 2:
        secondary = destinations[1]
        secondary.parent.mkdir(parents=True, exist_ok=True)
        secondary.symlink_to(os.path.relpath(primary, secondary.parent), target_is_directory=True)
        installed.append(secondary)
    return installed
