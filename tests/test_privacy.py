from __future__ import annotations

import re

import pytest

from freeform_to_markdown.privacy import redact_text, sanitize_filename

from .support import FAKE_PRIVATE_URL, FAKE_SECRET


def test_redaction_removes_synthetic_credentials_and_private_urls() -> None:
    source = (
        "Useful public note. "
        f"password=fixture-password-not-real token={FAKE_SECRET} {FAKE_PRIVATE_URL}"
    )
    redacted = redact_text(source)
    assert "Useful public note." in redacted
    assert "fixture-password-not-real" not in redacted
    assert FAKE_SECRET not in redacted
    assert FAKE_PRIVATE_URL not in redacted
    assert "REDACTED" in redacted.upper()


def test_redaction_is_deterministic_and_does_not_change_normal_numbers() -> None:
    source = "Scene 12 contains 4 objects at coordinates 320 by 180."
    assert redact_text(source) == source
    assert redact_text(source) == redact_text(source)


def test_redaction_removes_private_path_tokens_and_local_message_links() -> None:
    source = (
        "https://example.com/share/00000000-0000-4000-8000-000000000123 "
        "https://example.com/s/FixtureToken1234567890 "
        "message:%3Csynthetic-message-id%40example.invalid%3E"
    )
    redacted = redact_text(source)
    assert "00000000-0000-4000-8000-000000000123" not in redacted
    assert "FixtureToken1234567890" not in redacted
    assert "synthetic-message-id" not in redacted
    assert redacted.count("REDACTED") >= 3


def test_redaction_preserves_non_secret_descriptive_url_paths() -> None:
    source = "https://example.com/2026/08/how-to-archive-freeform-boards"
    assert redact_text(source) == source


def test_redaction_does_not_treat_sin_inside_an_ordinary_word_as_an_identifier() -> None:
    source = "code: missing-asset"
    assert redact_text(source) == source


@pytest.mark.parametrize(
    "value",
    [
        "OHIP: 0000 000 000 XX",
        "SIN 000-000-000",
        "Member ID: 00000000000",
        "Passport number: EXAMPLE 0000000",
    ],
)
def test_redaction_filters_contextual_sensitive_identifiers(value: str) -> None:
    redacted = redact_text(value)
    assert "REDACTED" in redacted
    assert not re.search(r"\d{6,}", redacted.replace(" ", "").replace("-", ""))


@pytest.mark.parametrize(
    ("unsafe", "expected_fragment"),
    [
        ("../escape.md", "escape"),
        ("folder/name.txt", "folder-name"),
        ("研究 图片 (final).png", "研究 图片 (final)"),
        ("CON", "CON"),
        ("  many   spaces  ", "many spaces"),
    ],
)
def test_sanitize_filename_is_safe_and_unicode_aware(unsafe: str, expected_fragment: str) -> None:
    sanitized = sanitize_filename(unsafe)
    assert expected_fragment in sanitized
    assert "/" not in sanitized
    assert "\\" not in sanitized
    assert sanitized not in {"", ".", ".."}
    assert not sanitized.startswith(".")
    assert len(sanitized.encode("utf-8")) <= 240
    assert not re.search(r"[\x00-\x1f]", sanitized)


def test_sanitize_filename_handles_empty_and_long_names() -> None:
    assert sanitize_filename("\x00\n\t")
    long_name = sanitize_filename("图" * 300 + ".png")
    assert len(long_name.encode()) <= 240
    assert long_name.endswith(".png")
