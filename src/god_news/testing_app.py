"""Deterministic browser-test/demo application; never used by production startup."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from god_news.api.app import create_app
from god_news.application.memory import MemoryCoordinator
from god_news.application.workflow import StoryWorkflow
from god_news.config import Environment, Settings
from god_news.container import AppContainer
from god_news.infrastructure.source_health import build_source_policies
from god_news.infrastructure.testing import (
    DeterministicFetcher,
    DeterministicSpeechSynthesizer,
    DeterministicTextGenerator,
    DeterministicVoiceProfileResolver,
    InMemoryMemoryProvider,
    InMemoryStoryRepository,
)
from god_news.sources.health import SourceHealthMonitor
from god_news.sources.registry import create_default_source_registry

settings = Settings(
    _env_file=None,
    environment=Environment.TEST,
    output_dir=Path("./data/offline-demo-outputs"),
    deepseek_api_key=SecretStr("offline-demo-not-a-real-key"),
)


async def build_testing_container(_: Settings) -> AppContainer:
    repository = InMemoryStoryRepository()
    fetcher = DeterministicFetcher()
    generator = DeterministicTextGenerator()
    memory_provider = InMemoryMemoryProvider()
    synthesizer = DeterministicSpeechSynthesizer(settings.output_dir)
    voice_resolver = DeterministicVoiceProfileResolver(settings.output_dir)
    source_normalizers = create_default_source_registry()
    source_health = SourceHealthMonitor(
        normalizers=source_normalizers,
        policies=build_source_policies(settings),
        probe=None,
    )
    workflow = StoryWorkflow(
        repository=repository,
        fetcher=fetcher,
        generator=generator,
        memory=MemoryCoordinator(memory_provider, recall_fail_open=True, recall_limit=5),
        synthesizer=synthesizer,
        source_normalizer=source_normalizers,
        voice_resolver=voice_resolver,
    )
    return AppContainer(
        settings=settings,
        repository=repository,
        fetcher=fetcher,
        generator=generator,
        memory_provider=memory_provider,
        synthesizer=synthesizer,
        workflow=workflow,
        source_normalizers=source_normalizers,
        source_health=source_health,
    )


app = create_app(settings, container_factory=build_testing_container)
