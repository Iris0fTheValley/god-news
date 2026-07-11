from __future__ import annotations

from typing import Literal

from god_news.sources.models import (
    DazhongSourceFields,
    ImageMediaAsset,
    MediaAsset,
    NormalizedSourceItem,
    RawDazhongImage,
    RawDazhongItem,
    RawDazhongVideo,
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


class DazhongSourceNormalizer:
    source: Literal["dazhong"] = "dazhong"
    raw_type: type[RawDazhongItem] = RawDazhongItem

    def normalize(self, item: RawDazhongItem, /) -> NormalizedSourceItem:
        canonical_url = canonicalize_http_url(item.canonical_url or item.url)
        title = normalize_text(item.title, preserve_paragraphs=False)
        content = normalize_text(item.body, preserve_paragraphs=True)
        author = normalize_optional_text(item.author)
        rights = build_rights(item.rights)
        media = deduplicate_media([self._extract_media(asset) for asset in item.media])
        return NormalizedSourceItem(
            source=SourcePlatform.DAZHONG,
            external_id=stable_external_id(SourcePlatform.DAZHONG, item.article_id),
            canonical_url=canonical_url,
            title=title,
            content_text=content,
            content_sha256=content_sha256(content),
            language=normalize_text(item.language, preserve_paragraphs=False),
            author=author,
            published_at=to_utc(item.published_at),
            media=media,
            attribution=build_attribution(
                source="dazhong",
                publisher=item.publisher,
                original_url=canonical_url,
                author=author,
            ),
            rights=rights,
            flags=build_flags(media=media, rights=rights, user_generated=False),
            source_fields=DazhongSourceFields(
                article_id=normalize_text(item.article_id, preserve_paragraphs=False),
                channel=normalize_optional_text(item.channel),
                region=normalize_optional_text(item.region),
                tags=normalize_tags(item.tags),
            ),
        )

    @staticmethod
    def _extract_media(asset: RawDazhongImage | RawDazhongVideo) -> MediaAsset:
        if isinstance(asset, RawDazhongImage):
            return ImageMediaAsset(
                url=canonical_media_url(asset.url),
                role=asset.role,
                alt_text=normalize_optional_text(asset.alt_text),
                credit=normalize_optional_text(asset.credit),
                width=asset.width,
                height=asset.height,
            )
        return VideoMediaAsset(
            url=canonical_media_url(asset.url),
            poster_url=(canonical_media_url(asset.poster_url) if asset.poster_url else None),
            caption=normalize_optional_text(asset.caption),
            credit=normalize_optional_text(asset.credit),
            duration_ms=asset.duration_ms,
        )
