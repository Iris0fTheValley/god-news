from __future__ import annotations

from typing import Protocol, TypeVar

from god_news.sources.models import (
    NormalizedSourceItem,
    RawSourceBase,
    RawSourceItem,
    SourceName,
)

RawSourceT = TypeVar("RawSourceT", bound=RawSourceBase)


class SourceNormalizer(Protocol[RawSourceT]):
    """Typed replacement seam between a source adapter and the core pipeline."""

    @property
    def source(self) -> SourceName: ...

    @property
    def raw_type(self) -> type[RawSourceT]: ...

    def normalize(self, item: RawSourceT, /) -> NormalizedSourceItem: ...


class SourceItemNormalizer(Protocol):
    """Application-facing dispatcher for all supported raw source contracts."""

    def normalize(self, item: RawSourceItem, /) -> NormalizedSourceItem: ...
