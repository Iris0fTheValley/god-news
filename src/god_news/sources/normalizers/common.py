from __future__ import annotations

from pydantic import AnyHttpUrl

from god_news.sources.models import (
    Attribution,
    ContentFlags,
    MediaAsset,
    RawRightsDeclaration,
    RightsMetadata,
    RightsStatus,
    SourceName,
)
from god_news.sources.text import canonicalize_http_url, normalize_optional_text, normalize_text


def canonical_media_url(value: AnyHttpUrl) -> str:
    return canonicalize_http_url(value)


def deduplicate_media(assets: list[MediaAsset]) -> list[MediaAsset]:
    seen: set[tuple[str, str]] = set()
    result: list[MediaAsset] = []
    for asset in assets:
        identity = (asset.kind, canonicalize_http_url(asset.url))
        if identity not in seen:
            seen.add(identity)
            result.append(asset)
    return result


def build_attribution(
    *,
    source: SourceName,
    publisher: str,
    original_url: str,
    author: str | None,
) -> Attribution:
    clean_publisher = normalize_text(publisher, preserve_paragraphs=False)
    clean_author = normalize_optional_text(author)
    attribution_text = clean_publisher
    if clean_author:
        attribution_text = f"{clean_author} — {clean_publisher}"
    return Attribution(
        source=source,
        publisher=clean_publisher,
        original_url=original_url,
        author=clean_author,
        attribution_text=attribution_text,
    )


def build_rights(declaration: RawRightsDeclaration) -> RightsMetadata:
    status = declaration.status
    requires_review = status in {RightsStatus.UNKNOWN, RightsStatus.PERMISSION_REQUIRED}
    if status == RightsStatus.ATTRIBUTION_LICENSE:
        requires_review = declaration.allows_republication is not True
    return RightsMetadata(
        status=status,
        copyright_holder=normalize_optional_text(declaration.copyright_holder),
        license_name=normalize_optional_text(declaration.license_name),
        license_url=declaration.license_url,
        terms_url=declaration.terms_url,
        allows_republication=declaration.allows_republication,
        allows_derivatives=declaration.allows_derivatives,
        requires_attribution=declaration.requires_attribution,
        requires_human_review=requires_review,
    )


def build_flags(
    *,
    media: list[MediaAsset],
    rights: RightsMetadata,
    user_generated: bool,
    nsfw: bool = False,
    spoiler: bool = False,
) -> ContentFlags:
    kinds = {asset.kind for asset in media}
    return ContentFlags(
        is_user_generated=user_generated,
        is_nsfw=nsfw,
        is_spoiler=spoiler,
        has_images="image" in kinds,
        has_video="video" in kinds,
        has_audio="audio" in kinds,
        requires_rights_review=rights.requires_human_review,
    )
