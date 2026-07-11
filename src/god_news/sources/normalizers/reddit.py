from __future__ import annotations

from typing import Literal

from god_news.sources.models import (
    ImageMediaAsset,
    MediaAsset,
    NormalizedSourceItem,
    RawRedditItem,
    RedditSourceFields,
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
    normalize_text,
    reddit_canonical_url,
    stable_external_id,
    to_utc,
)


class RedditSourceNormalizer:
    source: Literal["reddit"] = "reddit"
    raw_type: type[RawRedditItem] = RawRedditItem

    def normalize(self, item: RawRedditItem, /) -> NormalizedSourceItem:
        canonical_url = reddit_canonical_url(item.permalink)
        title = normalize_text(item.title, preserve_paragraphs=False)
        content = normalize_text(item.selftext, preserve_paragraphs=True) or title
        author = normalize_optional_text(item.author)
        rights = build_rights(item.rights)
        media: list[MediaAsset] = [
            ImageMediaAsset(
                url=canonical_media_url(image.url),
                role="thumbnail",
                width=image.width,
                height=image.height,
            )
            for image in item.preview_images
        ]
        if item.video is not None:
            media.append(
                VideoMediaAsset(
                    url=canonical_media_url(item.video.fallback_url),
                    poster_url=(
                        canonical_media_url(item.video.thumbnail_url)
                        if item.video.thumbnail_url
                        else None
                    ),
                    duration_ms=item.video.duration_ms,
                )
            )
        media = deduplicate_media(media)
        outbound_url = (
            canonicalize_http_url(item.outbound_url) if item.outbound_url is not None else None
        )
        return NormalizedSourceItem(
            source=SourcePlatform.REDDIT,
            external_id=stable_external_id(SourcePlatform.REDDIT, item.post_id),
            canonical_url=canonical_url,
            title=title,
            content_text=content,
            content_sha256=content_sha256(content),
            language=normalize_text(item.language, preserve_paragraphs=False),
            author=author,
            published_at=to_utc(item.created_utc),
            media=media,
            attribution=build_attribution(
                source="reddit",
                publisher=f"Reddit r/{normalize_text(item.subreddit, preserve_paragraphs=False)}",
                original_url=canonical_url,
                author=author,
            ),
            rights=rights,
            flags=build_flags(
                media=media,
                rights=rights,
                user_generated=True,
                nsfw=item.over_18,
                spoiler=item.spoiler,
            ),
            source_fields=RedditSourceFields(
                post_id=normalize_text(item.post_id, preserve_paragraphs=False),
                subreddit=normalize_text(item.subreddit, preserve_paragraphs=False),
                score=item.score,
                num_comments=item.num_comments,
                flair=normalize_optional_text(item.link_flair_text),
                locked=item.locked,
                is_self=item.is_self,
                outbound_url=outbound_url,
            ),
        )
