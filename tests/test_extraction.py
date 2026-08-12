from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import pytest
from pypdf import PdfWriter

from freeform_to_markdown import extraction


def _blank_pdf(path: Path, pages: int = 1) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as stream:
        writer.write(stream)


def test_image_ocr_gracefully_unavailable_off_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "fixture.png"
    image.write_bytes(b"synthetic image bytes")
    monkeypatch.setattr(extraction.platform, "system", lambda: "Linux")
    result = extraction.extract_image(image)
    assert result.kind == "image"
    assert result.method == "unavailable"
    assert not result.searchable
    assert "unavailable" in " ".join(result.warnings).lower()


def test_packaged_vision_helper_is_present() -> None:
    helper = extraction._vision_helper()
    assert helper.is_file()
    source = helper.read_text(encoding="utf-8")
    assert "VNRecognizeTextRequest" in source
    assert "PDFDocument" in source
    assert "http://" not in source and "https://" not in source


def test_vision_runner_uses_no_shell_and_parses_unicode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = tmp_path / "研究 image.png"
    image.write_bytes(b"synthetic")
    monkeypatch.setattr(extraction, "apple_vision_available", lambda: True)
    monkeypatch.setattr(extraction, "_vision_command", lambda: ("swift", "vision_ocr.swift"))
    seen: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {"ok": True, "pages": [{"page": 1, "text": "café 图片"}], "warnings": []}
            ),
            stderr="",
        )

    monkeypatch.setattr(extraction.subprocess, "run", fake_run)
    result = extraction.extract_image(image)
    assert result.text == "café 图片"
    assert result.method == "apple-vision"
    assert seen and seen[0][0] == "swift"
    assert str(image) in seen[0]


def test_blank_pdf_requests_vision_for_only_missing_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "blank.pdf"
    _blank_pdf(pdf, pages=2)
    requested: list[tuple[int, ...]] = []

    def fake_ocr(
        path: Path, *, pages: tuple[int, ...] = (), timeout: float = 180.0
    ) -> tuple[dict[int, str], tuple[str, ...]]:
        assert path == pdf
        assert timeout == 9.0
        requested.append(pages)
        return {1: "first page OCR", 2: "second page OCR"}, ()

    monkeypatch.setattr(extraction, "_vision_ocr", fake_ocr)
    result = extraction.extract_pdf(pdf, timeout=9.0)
    assert requested == [(1, 2)]
    assert result.method == "apple-vision"
    assert [page.page_number for page in result.pages] == [1, 2]
    assert result.metadata["page_count"] == 2
    assert result.metadata["ocr_pages"] == 2


def test_blank_pdf_records_explicit_warning_when_ocr_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "blank.pdf"
    _blank_pdf(pdf)
    monkeypatch.setattr(
        extraction,
        "_vision_ocr",
        lambda path, *, pages=(), timeout=180.0: ({}, ("Apple Vision OCR is unavailable",)),
    )
    result = extraction.extract_pdf(pdf)
    assert not result.searchable
    assert any("unavailable" in warning.lower() for warning in result.warnings)
    assert any("no searchable text" in warning.lower() for warning in result.warnings)


def test_corrupt_pdf_fails_without_leaking_its_path(tmp_path: Path) -> None:
    pdf = tmp_path / "private folder" / "fixture.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"not a PDF")
    result = extraction.extract_pdf(pdf)
    assert result.method == "failed"
    assert str(pdf) not in " ".join(result.warnings)


def test_pdf_page_tree_failure_retains_original_as_explicit_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "encrypted.pdf"
    pdf.write_bytes(b"%PDF-synthetic")

    class BrokenPages:
        def __len__(self) -> int:
            raise RuntimeError("synthetic page tree failure")

    class BrokenReader:
        pages = BrokenPages()

    monkeypatch.setattr(extraction, "PdfReader", lambda path: BrokenReader())
    result = extraction.extract_pdf(pdf)
    assert result.method == "failed"
    assert result.warnings == ("PDF extraction failed: RuntimeError",)
    assert str(pdf) not in result.warnings[0]


def test_wav_metadata_uses_local_standard_library_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio = tmp_path / "tone.wav"
    with wave.open(str(audio), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(b"\x00\x00" * 4_000)
    monkeypatch.setattr(extraction.shutil, "which", lambda command: None)
    result = extraction.technical_media_metadata(audio)
    assert result.method == "wave"
    assert result.metadata["duration_seconds"] == pytest.approx(0.5)
    assert result.metadata["sample_rate"] == 8_000
    assert result.metadata["channels"] == 1
    assert "path" not in result.metadata and "name" not in result.metadata


def test_ffprobe_metadata_is_allowlisted_and_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    movie = tmp_path / "fixture.mov"
    movie.write_bytes(b"synthetic movie")
    monkeypatch.setattr(extraction.shutil, "which", lambda command: "/usr/bin/ffprobe")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[0] == "/usr/bin/ffprobe"
        assert command[-1] == str(movie)
        assert "shell" not in kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "format": {
                        "duration": "1.25",
                        "format_name": "mov",
                        "bit_rate": "1000",
                        "tags": {"private": "must not propagate"},
                    },
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 640,
                            "height": 480,
                            "tags": {"location": "must not propagate"},
                        }
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(extraction.subprocess, "run", fake_run)
    result = extraction.technical_media_metadata(movie)
    assert result.method == "ffprobe"
    serialized = json.dumps(result.metadata)
    assert "must not propagate" not in serialized
    assert result.metadata["streams"] == [
        {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 480}
    ]


@pytest.mark.parametrize(
    ("suffix", "kind"),
    [(".png", "image"), (".pdf", "pdf"), (".mp4", "media"), (".bin", "unknown")],
)
def test_dispatch_is_suffix_based_and_never_uses_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    kind: str,
) -> None:
    path = tmp_path / f"fixture{suffix}"
    if suffix == ".pdf":
        _blank_pdf(path)
        monkeypatch.setattr(extraction, "_vision_ocr", lambda *args, **kwargs: ({}, ()))
    else:
        path.write_bytes(b"synthetic")
    monkeypatch.setattr(extraction.platform, "system", lambda: "Linux")
    monkeypatch.setattr(extraction.shutil, "which", lambda command: None)
    assert extraction.extract_asset(path).kind == kind
