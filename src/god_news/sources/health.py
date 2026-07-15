from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from pydantic import AnyHttpUrl, Field, model_validator

from god_news.domain.models import DomainModel, utc_now
from god_news.sources.models import SourceName
from god_news.sources.registry import SourceNormalizerRegistry

SourceAccessMethod = Literal[
    "official_api",
    "authorized_public_page",
    "typed_contract_only",
]


class SourceAdapterPolicy(DomainModel):
    """Configuration facts for a fixed source boundary.

    ``authorized`` means the operator has configured both the access mechanism
    and the required usage acknowledgement. It does not grant copyright or
    replace the per-item rights metadata carried by a normalized story.
    """

    source: SourceName
    enabled: bool
    configured: bool
    endpoint: AnyHttpUrl
    access_method: SourceAccessMethod
    authorized: bool
    notes: list[str] = Field(default_factory=list)


class SourceHealth(DomainModel):
    source: SourceName
    enabled: bool
    configured: bool
    authorized: bool
    reachable: bool | None
    contract_ok: bool
    access_method: SourceAccessMethod
    notes: list[str] = Field(default_factory=list)


class SourceHealthReport(DomainModel):
    checked_at: datetime = Field(default_factory=utc_now)
    network_probed: bool
    sources: list[SourceHealth] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def require_all_fixed_sources_once(self) -> SourceHealthReport:
        names = [item.source for item in self.sources]
        expected: set[SourceName] = {"dazhong", "reddit", "guardian", "pikabu"}
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("source health must contain each fixed source exactly once")
        return self


class SourceReachabilityProbe(Protocol):
    async def is_reachable(self, endpoint: str) -> bool: ...


class SourceHealthMonitor:
    def __init__(
        self,
        *,
        normalizers: SourceNormalizerRegistry,
        policies: Sequence[SourceAdapterPolicy],
        probe: SourceReachabilityProbe | None,
    ) -> None:
        self._normalizers = normalizers
        self._policies = tuple(policies)
        self._probe = probe
        names = [policy.source for policy in self._policies]
        expected: set[SourceName] = {"dazhong", "reddit", "guardian", "pikabu"}
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("source policies must contain each fixed source exactly once")

    async def report(self, *, probe_network: bool = False) -> SourceHealthReport:
        probe = self._probe
        should_probe = probe_network and probe is not None

        async def check(policy: SourceAdapterPolicy) -> SourceHealth:
            reachable: bool | None = None
            notes = list(policy.notes)
            if probe_network and self._probe is None:
                notes.append("network_probe_unavailable")
            elif should_probe and policy.enabled and policy.configured:
                assert probe is not None
                try:
                    reachable = await probe.is_reachable(str(policy.endpoint))
                except Exception:
                    reachable = False
                    notes.append("network_probe_failed")
            return SourceHealth(
                source=policy.source,
                enabled=policy.enabled,
                configured=policy.configured,
                authorized=policy.enabled and policy.configured and policy.authorized,
                reachable=reachable,
                contract_ok=policy.source in self._normalizers.registered_sources,
                access_method=policy.access_method,
                notes=notes,
            )

        sources = await asyncio.gather(*(check(policy) for policy in self._policies))
        return SourceHealthReport(network_probed=should_probe, sources=list(sources))
