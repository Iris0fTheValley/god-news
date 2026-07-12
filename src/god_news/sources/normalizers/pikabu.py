from __future__ import annotations

from typing import Literal

from god_news.sources.models import (
    ImageMediaAsset,
    MediaAsset,
    NormalizedSourceItem,
    PikabuImageBlock,
    PikabuQuoteBlock,
    PikabuSourceFields,
    PikabuTextBlock,
    PikabuVideoBlock,
    RawPikabuItem,
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


class PikabuSourceNormalizer:
    source: Literal["pikabu"] = "pikabu"
    raw_type: type[RawPikabuItem] = RawPikabuItem

    def normalize(self, item: RawPikabuItem, /) -> NormalizedSourceItem:
        canonical_url = canonicalize_http_url(item.url)
        title = normalize_text(item.title, preserve_paragraphs=False)
        paragraphs: list[str] = []
        media: list[MediaAsset] = []
        for block in item.blocks:
            if isinstance(block, PikabuTextBlock):
                paragraphs.append(normalize_text(block.text, preserve_paragraphs=True))
            elif isinstance(block, PikabuQuoteBlock):
                quote = normalize_text(block.text, preserve_paragraphs=True)
                quote_author = normalize_optional_text(block.author)
                paragraphs.append(f"> {quote} — {quote_author}" if quote_author else f"> {quote}")
            elif isinstance(block, PikabuImageBlock):
                media.append(
                    ImageMediaAsset(
                        url=canonical_media_url(block.url),
                        alt_text=normalize_optional_text(block.alt_text),
                        width=block.width,
                        height=block.height,
                    )
                )
            elif isinstance(block, PikabuVideoBlock):
                media.append(
                    VideoMediaAsset(
                        url=canonical_media_url(block.url),
                        poster_url=(
                            canonical_media_url(block.poster_url) if block.poster_url else None
                        ),
                        duration_ms=block.duration_ms,
                    )
                )
        content = "\n\n".join(paragraph for paragraph in paragraphs if paragraph) or title
        media = deduplicate_media(media)
        author = normalize_optional_text(item.author_username)
        rights = build_rights(item.rights)
        return NormalizedSourceItem(
            source=SourcePlatform.PIKABU,
            external_id=stable_external_id(SourcePlatform.PIKABU, item.story_id),
            canonical_url=canonical_url,
            title=title,
            content_text=content,
            content_sha256=content_sha256(content),
            language=normalize_text(item.language, preserve_paragraphs=False),
            author=author,
            published_at=to_utc(item.published_at),
            media=media,
            attribution=build_attribution(
                source="pikabu",
                publisher=item.publisher,
                original_url=canonical_url,
                author=author,
            ),
            rights=rights,
            flags=build_flags(
                media=media,
                rights=rights,
                user_generated=True,
                nsfw=item.is_nsfw,
            ),
            source_fields=PikabuSourceFields(
                story_id=normalize_text(item.story_id, preserve_paragraphs=False),
                rating=item.rating,
                comments_count=item.comments_count,
                tags=normalize_tags(item.tags),
                block_count=len(item.blocks),
            ),
        )
