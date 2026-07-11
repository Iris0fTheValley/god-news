from __future__ import annotations

from typing import Literal

from god_news.sources.models import (
    AudioMediaAsset,
    GuardianSourceFields,
    ImageMediaAsset,
    MediaAsset,
    NormalizedSourceItem,
    RawGuardianAudio,
    RawGuardianImage,
    RawGuardianItem,
    RawGuardianVideo,
    SourcePlatform,
    VideoMediaAsset,
)
from god_news.sources.normalizers.common import (
    build_attribution,
    build_flags,
    build_rights,
    canonical_media_url,
    deduplicate_media,
)
from god_news.sources.text import (
    canonicalize_http_url,
    content_sha256,
    normalize_optional_text,
    normalize_tags,
    normalize_text,
    stable_external_id,
    to_utc,
)


class GuardianSourceNormalizer:
    source: Literal["guardian"] = "guardian"
    raw_type: type[RawGuardianItem] = RawGuardianItem

    def normalize(self, item: RawGuardianItem, /) -> NormalizedSourceItem:
        canonical_url = canonicalize_http_url(item.web_url)
        title = normalize_text(item.web_title, preserve_paragraphs=False)
        content = normalize_text(item.body_text, preserve_paragraphs=True)
        author = normalize_optional_text(item.byline)
        rights = build_rights(item.rights)
        media = deduplicate_media([self._extract_media(asset) for asset in item.media])
        return NormalizedSourceItem(
            source=SourcePlatform.GUARDIAN,
            external_id=stable_external_id(SourcePlatform.GUARDIAN, item.article_id),
            canonical_url=canonical_url,
            title=title,
            content_text=content,
            content_sha256=content_sha256(content),
            language=normalize_text(item.language, preserve_paragraphs=False),
            author=author,
            published_at=to_utc(item.web_publication_date),
            media=media,
            attribution=build_attribution(
                source="guardian",
                publisher=item.publisher,
                original_url=canonical_url,
                author=author,
            ),
            rights=rights,
            flags=build_flags(media=media, rights=rights, user_generated=False),
            source_fields=GuardianSourceFields(
                article_id=normalize_text(item.article_id, preserve_paragraphs=False),
                section_id=normalize_optional_text(item.section_id),
                pillar_name=normalize_optional_text(item.pillar_name),
                trail_text=normalize_optional_text(item.trail_text, preserve_paragraphs=True),
                tags=normalize_tags(item.tags),
            ),
        )

    @staticmethod
    def _extract_media(
        asset: RawGuardianImage | RawGuardianVideo | RawGuardianAudio,
    ) -> MediaAsset:
        if isinstance(asset, RawGuardianImage):
            return ImageMediaAsset(
                url=canonical_media_url(asset.url),
                role=asset.role,
                alt_text=normalize_optional_text(asset.caption),
                credit=normalize_optional_text(asset.credit),
                width=asset.width,
                height=asset.height,
            )
        if isinstance(asset, RawGuardianVideo):
            return VideoMediaAsset(
                url=canonical_media_url(asset.url),
                poster_url=(canonical_media_url(asset.poster_url) if asset.poster_url else None),
                caption=normalize_optional_text(asset.caption),
                credit=normalize_optional_text(asset.credit),
                duration_ms=asset.duration_ms,
            )
        return AudioMediaAsset(
            url=canonical_media_url(asset.url),
            caption=normalize_optional_text(asset.caption),
            credit=normalize_optional_text(asset.credit),
            duration_ms=asset.duration_ms,
        )
