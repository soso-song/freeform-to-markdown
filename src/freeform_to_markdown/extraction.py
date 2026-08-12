"""Deterministic, local-only extraction helpers.

The module never sends content to a network service.  On macOS, image and
scanned-PDF OCR is delegated to the packaged Apple Vision Swift helper.  All
other platforms retain the original and return an explicit warning.
"""

from __future__ import annotations

import atexit
import json
import mimetypes
import platform
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pypdf import PdfReader

ImageSuffix = Literal[".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"]

_IMAGE_SUFFIXES = frozenset({".heic", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
_MEDIA_SUFFIXES = frozenset(
    {
        ".aac",
        ".aiff",
        ".avi",
        ".flac",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogg",
        ".wav",
        ".webm",
    }
)


@dataclass(frozen=True)
class PageText:
    """Searchable text for one one-indexed PDF page."""

    page_number: int
    text: str
    method: str


@dataclass(frozen=True)
class ExtractionResult:
    """Portable result suitable for a Markdown sidecar and asset manifest."""

    kind: str
    method: str
    text: str = ""
    pages: tuple[PageText, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def searchable(self) -> bool:
        return bool(self.text.strip())


def apple_vision_available() -> bool:
    """Return whether the local Apple Vision helper can run on this machine."""

    return platform.system() == "Darwin" and (
        shutil.which("swiftc") is not None or shutil.which("swift") is not None
    )


def _vision_helper() -> resources.abc.Traversable:
    return resources.files("freeform_to_markdown").joinpath("helpers", "vision_ocr.swift")


@cache
def _vision_command() -> tuple[str, ...]:
    """Compile the helper once per process, with the Swift interpreter as a fallback."""

    helper = _vision_helper()
    compiler = shutil.which("swiftc")
    interpreter = shutil.which("swift")
    with resources.as_file(helper) as helper_path:
        if compiler:
            build_directory = Path(tempfile.mkdtemp(prefix="ff2md-vision-helper-"))
            executable = build_directory / "vision-ocr"
            try:
                process = subprocess.run(
                    [compiler, str(helper_path), "-o", str(executable)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except (OSError, subprocess.SubprocessError):
                process = None
            if process is not None and process.returncode == 0 and executable.is_file():
                atexit.register(shutil.rmtree, build_directory, ignore_errors=True)
                return (str(executable),)
            shutil.rmtree(build_directory, ignore_errors=True)
        if interpreter:
            script_directory = Path(tempfile.mkdtemp(prefix="ff2md-vision-script-"))
            script = script_directory / "vision_ocr.swift"
            shutil.copyfile(helper_path, script)
            atexit.register(shutil.rmtree, script_directory, ignore_errors=True)
            return (interpreter, str(script))
    return ()


def _vision_ocr(
    path: Path,
    *,
    pages: tuple[int, ...] = (),
    timeout: float = 180.0,
) -> tuple[dict[int, str], tuple[str, ...]]:
    """Run the bundled helper and return one-indexed page text.

    Subprocess arguments are passed without a shell.  The helper's diagnostics
    intentionally avoid echoing the input path so manifests cannot inherit an
    absolute private path.
    """

    if not apple_vision_available():
        return {}, ("Apple Vision OCR is unavailable on this platform",)
    try:
        command = [*_vision_command(), str(path)]
        if not command[:-1]:
            return {}, ("Apple Vision OCR helper is unavailable",)
        if pages:
            command.extend(["--pages", ",".join(str(page) for page in pages)])
        process = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {}, (f"Apple Vision OCR failed: {error.__class__.__name__}",)
    try:
        payload = json.loads(process.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}, ("Apple Vision OCR returned invalid output",)
    if process.returncode != 0 or not isinstance(payload, dict) or not payload.get("ok"):
        message = payload.get("error") if isinstance(payload, dict) else None
        safe_message = str(message) if message else "helper failed"
        return {}, (f"Apple Vision OCR failed: {safe_message}",)
    raw_pages = payload.get("pages", [])
    result: dict[int, str] = {}
    if isinstance(raw_pages, list):
        for value in raw_pages:
            if not isinstance(value, dict):
                continue
            page_number = value.get("page")
            text = value.get("text")
            if isinstance(page_number, int) and isinstance(text, str):
                result[page_number] = text.strip()
    warnings = payload.get("warnings", [])
    safe_warnings = tuple(str(value) for value in warnings) if isinstance(warnings, list) else ()
    return result, safe_warnings


def extract_image(path: Path, *, timeout: float = 180.0) -> ExtractionResult:
    """OCR an image locally with Apple Vision when available."""

    path = Path(path)
    page_text, warnings = _vision_ocr(path, timeout=timeout)
    text = page_text.get(1, "")
    method = "apple-vision" if 1 in page_text else "unavailable"
    return ExtractionResult(
        kind="image",
        method=method,
        text=text,
        pages=(PageText(1, text, "apple-vision"),) if 1 in page_text else (),
        metadata=_basic_metadata(path),
        warnings=warnings,
    )


def extract_pdf(path: Path, *, timeout: float = 180.0) -> ExtractionResult:
    """Extract PDF text, using local Vision only for pages without a text layer."""

    path = Path(path)
    warnings: list[str] = []
    try:
        reader = PdfReader(path)
    except Exception as error:  # pypdf exposes several parser-specific exception classes
        return ExtractionResult(
            kind="pdf",
            method="failed",
            metadata=_basic_metadata(path),
            warnings=(f"PDF extraction failed: {error.__class__.__name__}",),
        )

    try:
        page_count = len(reader.pages)
    except Exception as error:
        return ExtractionResult(
            kind="pdf",
            method="failed",
            metadata=_basic_metadata(path),
            warnings=(f"PDF extraction failed: {error.__class__.__name__}",),
        )

    page_values: dict[int, PageText] = {}
    empty_pages: list[int] = []
    for page_number in range(1, page_count + 1):
        try:
            page = reader.pages[page_number - 1]
            value = (page.extract_text() or "").strip()
        except Exception as error:  # one damaged page must not discard other pages
            value = ""
            warnings.append(
                f"PDF page {page_number} text extraction failed: {error.__class__.__name__}"
            )
        if value:
            page_values[page_number] = PageText(page_number, value, "pdf-text-layer")
        else:
            empty_pages.append(page_number)

    if empty_pages:
        recognized, ocr_warnings = _vision_ocr(
            path,
            pages=tuple(empty_pages),
            timeout=timeout,
        )
        warnings.extend(ocr_warnings)
        for page_number in empty_pages:
            value = recognized.get(page_number, "").strip()
            if value:
                page_values[page_number] = PageText(page_number, value, "apple-vision")
            else:
                warnings.append(f"PDF page {page_number} has no searchable text")

    pages = tuple(page_values[index] for index in sorted(page_values))
    text = "\n\n".join(page.text for page in pages if page.text)
    methods = {page.method for page in pages}
    if methods == {"pdf-text-layer"}:
        method = "pdf-text-layer"
    elif methods == {"apple-vision"}:
        method = "apple-vision"
    elif methods:
        method = "pdf-text-layer+apple-vision"
    else:
        method = "unavailable"
    metadata = _basic_metadata(path)
    metadata.update(
        {
            "page_count": page_count,
            "text_layer_pages": sum(page.method == "pdf-text-layer" for page in pages),
            "ocr_pages": sum(page.method == "apple-vision" for page in pages),
        }
    )
    return ExtractionResult(
        kind="pdf",
        method=method,
        text=text,
        pages=pages,
        metadata=metadata,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _basic_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    media_type, _ = mimetypes.guess_type(path.name)
    return {
        "size_bytes": stat.st_size,
        "media_type": media_type or "application/octet-stream",
        "extension": path.suffix.casefold(),
    }


def _wave_metadata(path: Path) -> dict[str, Any]:
    try:
        with wave.open(str(path), "rb") as source:
            frame_rate = source.getframerate()
            frame_count = source.getnframes()
            return {
                "duration_seconds": frame_count / frame_rate if frame_rate else 0.0,
                "sample_rate": frame_rate,
                "channels": source.getnchannels(),
                "sample_width_bits": source.getsampwidth() * 8,
                "audio_codec": "pcm",
            }
    except (OSError, EOFError, wave.Error):
        return {}


def technical_media_metadata(path: Path, *, timeout: float = 30.0) -> ExtractionResult:
    """Collect local audio/video metadata with ffprobe or a WAV fallback."""

    path = Path(path)
    metadata = _basic_metadata(path)
    warnings: list[str] = []
    method = "basic-file-metadata"
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            process = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration,format_name,bit_rate:stream=codec_type,codec_name,width,height,sample_rate,channels,r_frame_rate",
                    "-of",
                    "json",
                    str(path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as error:
            warnings.append(f"ffprobe failed: {error.__class__.__name__}")
        else:
            try:
                payload = json.loads(process.stdout)
            except json.JSONDecodeError:
                payload = None
            if process.returncode == 0 and isinstance(payload, dict):
                format_data = payload.get("format")
                streams = payload.get("streams")
                if isinstance(format_data, dict):
                    metadata["format"] = {
                        key: format_data[key]
                        for key in ("duration", "format_name", "bit_rate")
                        if key in format_data
                    }
                if isinstance(streams, list):
                    metadata["streams"] = [
                        {
                            key: stream[key]
                            for key in (
                                "codec_type",
                                "codec_name",
                                "width",
                                "height",
                                "sample_rate",
                                "channels",
                                "r_frame_rate",
                            )
                            if key in stream
                        }
                        for stream in streams
                        if isinstance(stream, dict)
                    ]
                method = "ffprobe"
            else:
                warnings.append("ffprobe could not read media metadata")
    if method != "ffprobe" and path.suffix.casefold() == ".wav":
        wav_data = _wave_metadata(path)
        if wav_data:
            metadata.update(wav_data)
            method = "wave"
    if method == "basic-file-metadata":
        warnings.append("detailed local media metadata is unavailable")
    return ExtractionResult(
        kind="media",
        method=method,
        metadata=metadata,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def extract_asset(path: Path, *, timeout: float = 180.0) -> ExtractionResult:
    """Dispatch a local file to the deterministic extractor for its suffix."""

    path = Path(path)
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return extract_pdf(path, timeout=timeout)
    if suffix in _IMAGE_SUFFIXES:
        return extract_image(path, timeout=timeout)
    if suffix in _MEDIA_SUFFIXES:
        return technical_media_metadata(path, timeout=min(timeout, 30.0))
    return ExtractionResult(
        kind="unknown",
        method="unavailable",
        metadata=_basic_metadata(path),
        warnings=("no deterministic local extractor for this file type",),
    )


__all__ = [
    "ExtractionResult",
    "PageText",
    "apple_vision_available",
    "extract_asset",
    "extract_image",
    "extract_pdf",
    "technical_media_metadata",
]
