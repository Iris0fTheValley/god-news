from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from god_news.sources.text import content_sha256

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


SourceName = Literal["dazhong", "reddit", "guardian", "pikabu"]


class SourcePlatform:
    """Stable source discriminator values.

    This deliberately is not an Enum: Literal values remain friendly to external
    JSON producers while Pydantic still validates every supported source.
    """

    DAZHONG = "dazhong"
    REDDIT = "reddit"
    GUARDIAN = "guardian"
    PIKABU = "pikabu"


class StrictSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RightsStatus:
    UNKNOWN = "unknown"
    PERMISSION_REQUIRED = "permission_required"
    ATTRIBUTION_LICENSE = "attribution_license"
    PUBLIC_DOMAIN = "public_domain"


class RawRightsDeclaration(StrictSourceModel):
    status: Literal[
        "unknown",
        "permission_required",
        "attribution_license",
        "public_domain",
    ] = "unknown"
    copyright_holder: str | None = None
    license_name: str | None = None
    license_url: AnyHttpUrl | None = None
    terms_url: AnyHttpUrl | None = None
    allows_republication: bool | None = None
    allows_derivatives: bool | None = None
    requires_attribution: bool = True

    @model_validator(mode="after")
    def require_license_for_attribution_status(self) -> RawRightsDeclaration:
        if self.status == RightsStatus.ATTRIBUTION_LICENSE and not self.license_name:
            raise ValueError("attribution_license requires license_name")
        return self


class RawSourceBase(StrictSourceModel):
    source: str
    rights: RawRightsDeclaration = Field(default_factory=RawRightsDeclaration)


class RawDazhongImage(StrictSourceModel):
    kind: Literal["image"] = "image"
    url: AnyHttpUrl
    role: Literal["main", "body", "thumbnail"] = "body"
    alt_text: str | None = None
    credit: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class RawDazhongVideo(StrictSourceModel):
    kind: Literal["video"] = "video"
    url: AnyHttpUrl
    poster_url: AnyHttpUrl | None = None
    caption: str | None = None
    credit: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)


RawDazhongMedia = Annotated[RawDazhongImage | RawDazhongVideo, Field(discriminator="kind")]


class RawDazhongItem(RawSourceBase):
    source: Literal["dazhong"] = "dazhong"
    article_id: NonBlankStr
    url: AnyHttpUrl
    canonical_url: AnyHttpUrl | None = None
    title: NonBlankStr
    body: NonBlankStr
    author: str | None = None
    publisher: NonBlankStr = "大众新闻"
    published_at: AwareDatetime
    language: NonBlankStr = "zh-CN"
    channel: str | None = None
    region: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=100)
    media: list[RawDazhongMedia] = Field(default_factory=list, max_length=100)


class RawRedditVideo(StrictSourceModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: Literal["video"] = "video"
    fallback_url: AnyHttpUrl
    thumbnail_url: AnyHttpUrl | None = None
    duration_ms: int | None = Field(default=None, gt=0)


class RawRedditPreviewImage(StrictSourceModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    url: AnyHttpUrl
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class RawRedditItem(RawSourceBase):
    """Sanitized Reddit adapter contract.

    Reddit adds fields without notice. Unknown keys are intentionally ignored at
    this boundary; every field used downstream remains explicitly declared.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source: Literal["reddit"] = "reddit"
    post_id: NonBlankStr
    permalink: NonBlankStr
    title: NonBlankStr
    selftext: str = ""
    author: str | None = None
    created_utc: AwareDatetime
    subreddit: NonBlankStr
    score: int = 0
    num_comments: int = Field(default=0, ge=0)
    link_flair_text: str | None = None
    over_18: bool = False
    spoiler: bool = False
    locked: bool = False
    is_self: bool = True
    outbound_url: AnyHttpUrl | None = None
    video: RawRedditVideo | None = None
    preview_images: list[RawRedditPreviewImage] = Field(default_factory=list, max_length=20)
    language: NonBlankStr = "en"


class RawGuardianImage(StrictSourceModel):
    kind: Literal["image"] = "image"
    url: AnyHttpUrl
    role: Literal["main", "body", "thumbnail"] = "body"
    caption: str | None = None
    credit: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class RawGuardianVideo(StrictSourceModel):
    kind: Literal["video"] = "video"
    url: AnyHttpUrl
    poster_url: AnyHttpUrl | None = None
    caption: str | None = None
    credit: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)


class RawGuardianAudio(StrictSourceModel):
    kind: Literal["audio"] = "audio"
    url: AnyHttpUrl
    caption: str | None = None
    credit: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)


RawGuardianMedia = Annotated[
    RawGuardianImage | RawGuardianVideo | RawGuardianAudio,
    Field(discriminator="kind"),
]


class RawGuardianItem(RawSourceBase):
    source: Literal["guardian"] = "guardian"
    article_id: NonBlankStr
    web_url: AnyHttpUrl
    web_title: NonBlankStr
    body_text: NonBlankStr
    byline: str | None = None
    web_publication_date: AwareDatetime
    section_id: str | None = None
    pillar_name: str | None = None
    trail_text: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=100)
    media: list[RawGuardianMedia] = Field(default_factory=list, max_length=100)
    language: NonBlankStr = "en"
    publisher: NonBlankStr = "The Guardian"


class PikabuTextBlock(StrictSourceModel):
    kind: Literal["text"] = "text"
    text: NonBlankStr


class PikabuQuoteBlock(StrictSourceModel):
    kind: Literal["quote"] = "quote"
    text: NonBlankStr
    author: str | None = None


class PikabuImageBlock(StrictSourceModel):
    kind: Literal["image"] = "image"
    url: AnyHttpUrl
    alt_text: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class PikabuVideoBlock(StrictSourceModel):
    kind: Literal["video"] = "video"
    url: AnyHttpUrl
    poster_url: AnyHttpUrl | None = None
    duration_ms: int | None = Field(default=None, gt=0)


PikabuBlock = Annotated[
    PikabuTextBlock | PikabuQuoteBlock | PikabuImageBlock | PikabuVideoBlock,
    Field(discriminator="kind"),
]


class RawPikabuItem(RawSourceBase):
    source: Literal["pikabu"] = "pikabu"
    story_id: NonBlankStr
    url: AnyHttpUrl
    title: NonBlankStr
    author_username: str | None = None
    published_at: AwareDatetime
    blocks: list[PikabuBlock] = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=100)
    rating: int = 0
    comments_count: int = Field(default=0, ge=0)
    is_nsfw: bool = False
    language: NonBlankStr = "ru"
    publisher: NonBlankStr = "Pikabu"


RawSourceItem = Annotated[
    RawDazhongItem | RawRedditItem | RawGuardianItem | RawPikabuItem,
    Field(discriminator="source"),
]
RAW_SOURCE_ITEM_ADAPTER: TypeAdapter[RawSourceItem] = TypeAdapter(RawSourceItem)


class ImageMediaAsset(StrictSourceModel):
    kind: Literal["image"] = "image"
    url: AnyHttpUrl
    role: Literal["main", "body", "thumbnail"] = "body"
    alt_text: str | None = None
    credit: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)


class VideoMediaAsset(StrictSourceModel):
    kind: Literal["video"] = "video"
    url: AnyHttpUrl
    poster_url: AnyHttpUrl | None = None
    caption: str | None = None
    credit: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)


class AudioMediaAsset(StrictSourceModel):
    kind: Literal["audio"] = "audio"
    url: AnyHttpUrl
    caption: str | None = None
    credit: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)


MediaAsset = Annotated[
    ImageMediaAsset | VideoMediaAsset | AudioMediaAsset,
    Field(discriminator="kind"),
]


class Attribution(StrictSourceModel):
    source: SourceName
    publisher: NonBlankStr
    original_url: AnyHttpUrl
    author: str | None = None
    attribution_text: NonBlankStr


class RightsMetadata(StrictSourceModel):
    status: Literal[
        "unknown",
        "permission_required",
        "attribution_license",
        "public_domain",
    ]
    copyright_holder: str | None = None
    license_name: str | None = None
    license_url: AnyHttpUrl | None = None
    terms_url: AnyHttpUrl | None = None
    allows_republication: bool | None = None
    allows_derivatives: bool | None = None
    requires_attribution: bool
    requires_human_review: bool


class ContentFlags(StrictSourceModel):
    is_user_generated: bool
    is_nsfw: bool = False
    is_spoiler: bool = False
    has_images: bool = False
    has_video: bool = False
    has_audio: bool = False
    requires_rights_review: bool = True


class DazhongSourceFields(StrictSourceModel):
    source: Literal["dazhong"] = "dazhong"
    article_id: NonBlankStr
    channel: str | None = None
    region: str | None = None
    tags: list[NonBlankStr] = Field(default_factory=list, max_length=100)


class RedditSourceFields(StrictSourceModel):
    source: Literal["reddit"] = "reddit"
    post_id: NonBlankStr
    subreddit: NonBlankStr
    score: int
    num_comments: int = Field(ge=0)
    flair: str | None = None
    locked: bool
    is_self: bool
    outbound_url: AnyHttpUrl | None = None


class GuardianSourceFields(StrictSourceModel):
    source: Literal["guardian"] = "guardian"
    article_id: NonBlankStr
    section_id: str | None = None
    pillar_name: str | None = None
    trail_text: str | None = None
    tags: list[NonBlankStr] = Field(default_factory=list, max_length=100)


class PikabuSourceFields(StrictSourceModel):
    source: Literal["pikabu"] = "pikabu"
    story_id: NonBlankStr
    rating: int
    comments_count: int = Field(ge=0)
    tags: list[NonBlankStr] = Field(default_factory=list, max_length=100)
    block_count: int = Field(ge=1)


SourceSpecificFields = Annotated[
    DazhongSourceFields | RedditSourceFields | GuardianSourceFields | PikabuSourceFields,
    Field(discriminator="source"),
]


class NormalizedSourceItem(StrictSourceModel):
    schema_version: Literal["1.0"] = "1.0"
    source: SourceName
    external_id: NonBlankStr
    canonical_url: AnyHttpUrl
    title: NonBlankStr
    content_text: NonBlankStr
    content_sha256: Sha256Hex
    language: NonBlankStr
    author: str | None = None
    published_at: datetime
    media: list[MediaAsset] = Field(default_factory=list, max_length=200)
    attribution: Attribution
    rights: RightsMetadata
    flags: ContentFlags
    source_fields: SourceSpecificFields

    @field_validator("published_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("published_at must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_derived_fields(self) -> NormalizedSourceItem:
        if self.source_fields.source != self.source:
            raise ValueError("source_fields discriminator must match source")
        if self.attribution.source != self.source:
            raise ValueError("attribution discriminator must match source")
        if self.content_sha256 != content_sha256(self.content_text):
            raise ValueError("content_sha256 must match normalized content_text")
        kinds = {asset.kind for asset in self.media}
        expected = {
            "image": self.flags.has_images,
            "video": self.flags.has_video,
            "audio": self.flags.has_audio,
        }
        if any((kind in kinds) != present for kind, present in expected.items()):
            raise ValueError("media flags must match media assets")
        if self.flags.requires_rights_review != self.rights.requires_human_review:
            raise ValueError("rights review flags must agree")
        return self


def parse_raw_source_json(payload: str | bytes) -> RawSourceItem:
    """Validate an external JSON payload without exposing a mapping boundary."""

    return RAW_SOURCE_ITEM_ADAPTER.validate_json(payload)


def decode_windows_1251(payload: bytes) -> str:
    """Decode legacy Cyrillic bytes strictly; malformed input fails closed."""

    return payload.decode("windows-1251")


def parse_pikabu_windows_1251_json(payload: bytes) -> RawPikabuItem:
    """Decode a legacy Pikabu payload strictly and validate its typed contract."""

    return RawPikabuItem.model_validate_json(decode_windows_1251(payload))
