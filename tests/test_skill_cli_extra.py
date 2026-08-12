from __future__ import annotations

from pathlib import Path

import pytest

from freeform_to_markdown import archive as archive_module
from freeform_to_markdown.cli import _select_interactive, main
from freeform_to_markdown.models import BoardSummary
from freeform_to_markdown.skill import bundled_skill, install_skill
from freeform_to_markdown.source import BoardNotFoundError


class _TTY:
    def isatty(self) -> bool:
        return True


class _BoardSource:
    def __init__(self, boards: list[BoardSummary]) -> None:
        self._boards = boards

    def list_boards(self) -> list[BoardSummary]:
        return self._boards


def test_interactive_board_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    board = BoardSummary("00000000-0000-4000-8000-000000000001", "Example", 3, 1, None)
    monkeypatch.setattr("sys.stdin", _TTY())
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")
    assert _select_interactive(_BoardSource([board])) == board.board_id  # type: ignore[arg-type]


def test_interactive_board_selection_rejects_empty_and_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin", _TTY())
    with pytest.raises(BoardNotFoundError, match="no Freeform boards"):
        _select_interactive(_BoardSource([]))  # type: ignore[arg-type]
    board = BoardSummary("00000000-0000-4000-8000-000000000001", "Example", 3, 1, None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "99")
    with pytest.raises(BoardNotFoundError, match="invalid board"):
        _select_interactive(_BoardSource([board]))  # type: ignore[arg-type]


def test_skill_installer_copies_one_source_and_symlinks_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "user-home"))
    installed = install_skill("both")
    assert installed[0].joinpath("SKILL.md").is_file()
    assert installed[1].is_symlink()
    assert installed[1].resolve() == installed[0].resolve()
    with pytest.raises(FileExistsError):
        install_skill("codex")


def test_skill_installer_validation_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bundled_skill().joinpath("SKILL.md").is_file()
    with pytest.raises(ValueError, match="target"):
        install_skill("invalid")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    assert main(["install-skill", "--target", "codex"]) == 0
    assert "freeform-to-markdown" in capsys.readouterr().out


def test_local_extractors_cover_text_and_unavailable_media(tmp_path: Path) -> None:
    text_file = tmp_path / "note.txt"
    text_file.write_text("Useful note token=EXAMPLE_SECRET", encoding="utf-8")
    result = archive_module._extract_asset(text_file)
    assert "Useful note" in result.text
    assert "EXAMPLE_SECRET" in result.text
    assert result.warnings == ()

    image = tmp_path / "image.png"
    image.write_bytes(b"synthetic")
    assert archive_module._extract_asset(image).warnings
    unknown = tmp_path / "data.bin"
    unknown.write_bytes(b"synthetic")
    assert "no deterministic local extractor" in archive_module._extract_asset(unknown).warnings[0]
