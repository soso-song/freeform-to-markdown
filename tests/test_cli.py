from __future__ import annotations

import json
from pathlib import Path

import yaml

from freeform_to_markdown.cli import main

from .support import BOARD_TITLE, BOARD_UUID, TEXT_UUID, SyntheticSource


def _set_source_environment(monkeypatch: object, source: SyntheticSource) -> None:
    monkeypatch.setenv("FREEFORM_DB_PATH", str(source.database))  # type: ignore[attr-defined]
    monkeypatch.setenv("FREEFORM_ASSETS_PATH", str(source.assets))  # type: ignore[attr-defined]


def test_doctor_and_boards_commands_use_synthetic_environment(
    monkeypatch: object,
    capsys: object,
    synthetic_source: SyntheticSource,
) -> None:
    _set_source_environment(monkeypatch, synthetic_source)
    assert main(["doctor"]) == 0
    doctor_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "16" in doctor_output
    assert "verified" in doctor_output.lower()

    assert main(["boards"]) == 0
    boards_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert BOARD_TITLE in boards_output
    assert str(BOARD_UUID) in boards_output


def test_archive_then_verify_cli_round_trip(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
    synthetic_source: SyntheticSource,
) -> None:
    _set_source_environment(monkeypatch, synthetic_source)
    output = tmp_path / "archive destination"
    assert main(["archive", "--board", BOARD_TITLE, "--output", str(output)]) == 0
    archive_output = capsys.readouterr().out.strip()  # type: ignore[attr-defined]
    archive_path = Path(archive_output.splitlines()[-1])
    assert archive_path.is_dir()
    assert archive_path.is_relative_to(output)

    assert main(["verify", str(archive_path)]) == 0
    verify_output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "pass" in verify_output.lower() or "verified" in verify_output.lower()


def test_refine_cli_accepts_documented_scene_map(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
    synthetic_source: SyntheticSource,
) -> None:
    _set_source_environment(monkeypatch, synthetic_source)
    output = tmp_path / "output"
    assert main(["archive", "--board", BOARD_TITLE, "-o", str(output)]) == 0
    archive_path = Path(capsys.readouterr().out.strip().splitlines()[-1])  # type: ignore[attr-defined]
    scene_map = tmp_path / "scene-map.yml"
    scene_map.write_text(
        yaml.safe_dump(
            {
                "scenes": [
                    {
                        "id": "notes",
                        "title": "Curated Notes",
                        "object_ids": [str(TEXT_UUID)],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert main(["refine", str(archive_path), "--scene-map", str(scene_map)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    objects_path = archive_path / "Manifest" / "objects.jsonl"
    records = [json.loads(line) for line in objects_path.read_text().splitlines()]
    record = next(item for item in records if item["object_id"] == str(TEXT_UUID))
    assert record["scene"] == "notes"


def test_unknown_schema_returns_nonzero_without_traceback(
    monkeypatch: object,
    capsys: object,
    unknown_schema_source: SyntheticSource,
) -> None:
    _set_source_environment(monkeypatch, unknown_schema_source)
    assert main(["boards"]) != 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "999" in captured.err
    assert "traceback" not in captured.err.lower()


def test_archive_cli_keeps_incomplete_archive_but_returns_nonzero(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
    adverse_source: SyntheticSource,
) -> None:
    _set_source_environment(monkeypatch, adverse_source)
    output = tmp_path / "incomplete-output"
    assert main(["archive", "--board", BOARD_TITLE, "--output", str(output)]) == 1
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    archive = Path(captured.out.strip().splitlines()[-1])
    assert archive.is_dir()
    assert (archive / "Manifest" / "verification.json").is_file()
    assert "verification failed" in captured.err.lower()
