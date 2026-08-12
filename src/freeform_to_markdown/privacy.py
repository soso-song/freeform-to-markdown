"""Deterministic privacy and path-safety helpers."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_SECRET_KEYS = {
    "access_token",
    "accessid",
    "access_id",
    "apikey",
    "api_key",
    "auth",
    "authkey",
    "code",
    "credential",
    "jwt",
    "key",
    "passcode",
    "password",
    "secret",
    "session",
    "sid",
    "sig",
    "signature",
    "ticket",
    "token",
}
_URL = re.compile(r"https?://[^\s<>\])}]+", re.IGNORECASE)
_PRIVATE_SCHEME = re.compile(
    r"(?i)\b(?:facetime|freeform|message|sms|tel|x-apple-reminderkit):[^\s<>]+"
)
_UUID_PATH_SEGMENT = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CREDENTIAL = re.compile(
    r"(?i)\b(password|passcode|token|api[_ -]?key|secret|session)\s*[:=]\s*[^\s,;]+"
)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "[PRIVATE URL REDACTED]"
    query = parse_qsl(parts.query, keep_blank_values=True)
    segments = parts.path.split("/")
    private_marker = False
    safe_segments: list[str] = []
    for segment in segments:
        decoded_segment = unquote(segment)
        compact = re.sub(r"[-_.~]", "", decoded_segment)
        tokenish = (
            _UUID_PATH_SEGMENT.fullmatch(decoded_segment) is not None
            or (
                len(compact) >= 20
                and compact.isalnum()
                and any(character.isalpha() for character in compact)
                and any(character.isdigit() for character in compact)
            )
            or (private_marker and len(compact) >= 10)
        )
        safe_segments.append("[REDACTED]" if tokenish else segment)
        private_marker = segment.casefold() in {"d", "document", "s", "share"}
    path = "/".join(safe_segments)
    sensitive = (
        bool(parts.username or parts.password)
        or any(key.casefold() in _SECRET_KEYS for key, _ in query)
        or path != parts.path
    )
    private_host = parts.hostname is not None and parts.hostname.casefold().endswith(".invalid")
    if private_host:
        return "[PRIVATE URL REDACTED]"
    safe_query = [
        (key, "[REDACTED]") if key.casefold() in _SECRET_KEYS else (key, value)
        for key, value in query
    ]
    if sensitive:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, host, path, urlencode(safe_query), ""))
    return raw


def redact_text(text: str) -> str:
    """Remove common credentials and private URL material from searchable text."""

    if not text:
        return text
    redacted = _PRIVATE_SCHEME.sub("[PRIVATE URL REDACTED]", text)
    redacted = _URL.sub(_redact_url, redacted)
    redacted = _CREDENTIAL.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)\b(meeting\s*id|member\s*id|passport(?:\s*number)?|ohip|sin)\b"
        r"\s*[:=]?\s*[A-Z0-9 -]{6,}",
        lambda match: f"{match.group(1)} [REDACTED]",
        redacted,
    )
    return redacted


def _trim_utf8(value: str, limit: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    return encoded[:limit].decode("utf-8", errors="ignore")


def sanitize_filename(value: str, *, fallback: str = "untitled", max_bytes: int = 240) -> str:
    """Return a Unicode-preserving basename which cannot escape its directory."""

    raw = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    raw = raw.replace("/", "-").replace("\\", "-").replace(":", "-")
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    raw = raw or fallback
    suffix = Path(raw).suffix
    if suffix and len(suffix.encode("utf-8")) < max_bytes // 2:
        stem_limit = max_bytes - len(suffix.encode("utf-8"))
        stem = _trim_utf8(raw[: -len(suffix)], stem_limit).rstrip(" .") or fallback
        raw = stem + suffix
    else:
        raw = _trim_utf8(raw, max_bytes).rstrip(" .") or fallback
    if raw in {".", ".."} or raw.startswith("."):
        raw = "item-" + raw.lstrip(".")
    return raw


def safe_join(root: Path, relative: str | Path) -> Path:
    """Resolve a child path and reject traversal outside the selected archive root."""

    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("archive path escapes output root")
    return candidate
