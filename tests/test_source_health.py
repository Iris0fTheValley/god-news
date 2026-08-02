from __future__ import annotations

import pytest

from god_news.config import Settings
from god_news.infrastructure.source_health import build_source_policies
from god_news.sources.health import SourceHealthMonitor
from god_news.sources.registry import create_default_source_registry


class DeterministicProbe:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def is_reachable(self, endpoint: str) -> bool:
        self.calls.append(endpoint)
        return "pikabu" not in endpoint


@pytest.mark.asyncio
async def test_source_health_distinguishes_all_four_dimensions() -> None:
    settings = Settings(
        _env_file=None,
        source_dazhong_enabled=False,
        source_reddit_client_id="client",
        source_reddit_client_secret="secret",
        source_reddit_user_agent="god-news-test/1.0 by test-operator",
        source_reddit_api_use_authorized=True,
        source_guardian_api_key="guardian-key",
        source_guardian_ai_use_authorized=False,
        source_pikabu_public_page_use_authorized=True,
    )
    probe = DeterministicProbe()
    monitor = SourceHealthMonitor(
        normalizers=create_default_source_registry(),
        policies=build_source_policies(settings),
        probe=probe,
    )

    report = await monitor.report(probe_network=True)
    by_source = {item.source: item for item in report.sources}

    assert report.network_probed is True
    assert by_source["dazhong"].enabled is False
    assert by_source["dazhong"].configured is True
    assert by_source["dazhong"].authorized is False
    assert by_source["dazhong"].reachable is None
    assert by_source["reddit"].configured is True
    assert by_source["reddit"].authorized is True
    assert by_source["reddit"].reachable is True
    assert by_source["guardian"].authorized is False
    assert by_source["guardian"].reachable is True
    assert by_source["pikabu"].authorized is True
    assert by_source["pikabu"].reachable is False
    assert all(item.contract_ok for item in report.sources)
    assert len(probe.calls) == 3


@pytest.mark.asyncio
async def test_network_probe_request_without_probe_is_explicitly_unknown() -> None:
    settings = Settings(_env_file=None)
    monitor = SourceHealthMonitor(
        normalizers=create_default_source_registry(),
        policies=build_source_policies(settings),
        probe=None,
    )

    report = await monitor.report(probe_network=True)

    assert report.network_probed is False
    assert all(item.reachable is None for item in report.sources)
    assert all("network_probe_unavailable" in item.notes for item in report.sources)
