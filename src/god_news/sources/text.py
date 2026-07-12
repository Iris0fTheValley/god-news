from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AnyHttpUrl

_INLINE_WHITESPACE = re.compile(r"[^\S\r\n]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_TRACKING_KEYS = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_source",
    }
)


def normalize_text(value: str, *, preserve_paragraphs: bool = True) -> str:
    """Apply deterministic Unicode NFKC and whitespace normalization."""

    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character
        for character in normalized
        if character in {"\n", "\t"} or unicodedata.category(character) != "Cc"
    )
    if not preserve_paragraphs:
        return " ".join(normalized.split())
    lines = [_INLINE_WHITESPACE.sub(" ", line).strip() for line in normalized.split("\n")]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def normalize_optional_text(value: str | None, *, preserve_paragraphs: bool = False) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value, preserve_paragraphs=preserve_paragraphs)
    return normalized or None


def normalize_tags(values: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for value in values:
        cleaned = normalize_text(value, preserve_paragraphs=False)
        if cleaned:
            unique.setdefault(cleaned.casefold(), cleaned)
    return sorted(unique.values(), key=str.casefold)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source timestamp must include an explicit timezone")
    return value.astimezone(UTC)


def content_sha256(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def stable_external_id(source: str, native_id: str) -> str:
    cleaned = normalize_text(native_id, preserve_paragraphs=False)
    if not cleaned:
        raise ValueError("native source id cannot be blank")
    return f"{source}:{cleaned}"


def canonicalize_http_url(value: str | AnyHttpUrl) -> str:
    """Canonicalize identity-safe URL components without changing path semantics."""

    parts = urlsplit(str(value))
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("canonical URL must be absolute HTTP(S)")
    if parts.username is not None or parts.password is not None:
        raise ValueError("canonical URL cannot contain credentials")

    host = parts.hostname.encode("idna").decode("ascii").lower()
    port = parts.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    authority_host = f"[{host}]" if ":" in host else host
    netloc = authority_host if port is None or default_port else f"{authority_host}:{port}"

    retained_query = [
        (key, query_value)
        for key, query_value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_KEYS
    ]
    retained_query.sort(key=lambda pair: (pair[0].casefold(), pair[1]))
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(retained_query), ""))


def reddit_canonical_url(permalink: str) -> str:
    parts = urlsplit(permalink)
    if parts.scheme or parts.netloc:
        candidate = permalink
    else:
        path = permalink if permalink.startswith("/") else f"/{permalink}"
        candidate = f"https://www.reddit.com{path}"
    return canonicalize_http_url(candidate)
