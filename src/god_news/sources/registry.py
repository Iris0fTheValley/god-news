from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol

from god_news.sources.models import (
    NormalizedSourceItem,
    RawSourceBase,
    RawSourceItem,
    SourceName,
    parse_raw_source_json,
)
from god_news.sources.normalizers import (
    DazhongSourceNormalizer,
    GuardianSourceNormalizer,
    PikabuSourceNormalizer,
    RedditSourceNormalizer,
)
from god_news.sources.protocols import RawSourceT, SourceNormalizer


class _RegisteredNormalizer(Protocol):
    @property
    def source(self) -> SourceName: ...

    def normalize_checked(self, item: RawSourceBase, /) -> NormalizedSourceItem: ...


@dataclass(frozen=True, slots=True)
class _TypedRegistration(Generic[RawSourceT]):
    delegate: SourceNormalizer[RawSourceT]

    @property
    def source(self) -> SourceName:
        return self.delegate.source

    def normalize_checked(self, item: RawSourceBase, /) -> NormalizedSourceItem:
        if not isinstance(item, self.delegate.raw_type):
            raise TypeError(
                f"normalizer {self.source!r} expected {self.delegate.raw_type.__name__}, "
                f"received {type(item).__name__}"
            )
        return self.delegate.normalize(item)


class SourceNormalizerRegistry:
    """Runtime dispatch that retains type checks at registration and invocation."""

    def __init__(self) -> None:
        self._registrations: dict[SourceName, _RegisteredNormalizer] = {}

    def register(self, normalizer: SourceNormalizer[RawSourceT], /) -> None:
        if normalizer.source in self._registrations:
            raise ValueError(f"normalizer already registered for {normalizer.source!r}")
        registration: _RegisteredNormalizer = _TypedRegistration(normalizer)
        self._registrations[normalizer.source] = registration

    def normalize(self, item: RawSourceItem, /) -> NormalizedSourceItem:
        registration = self._registrations.get(item.source)
        if registration is None:
            raise LookupError(f"no normalizer registered for {item.source!r}")
        return registration.normalize_checked(item)

    def normalize_json(self, payload: str | bytes, /) -> NormalizedSourceItem:
        return self.normalize(parse_raw_source_json(payload))

    @property
    def registered_sources(self) -> frozenset[SourceName]:
        return frozenset(self._registrations)


def create_default_source_registry() -> SourceNormalizerRegistry:
    registry = SourceNormalizerRegistry()
    registry.register(DazhongSourceNormalizer())
    registry.register(RedditSourceNormalizer())
    registry.register(GuardianSourceNormalizer())
    registry.register(PikabuSourceNormalizer())
    return registry
