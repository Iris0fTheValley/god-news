from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import SecretStr

from god_news.application.memory import MemoryCoordinator
from god_news.application.workflow import StoryWorkflow
from god_news.config import Environment, Settings
from god_news.container import AppContainer
from god_news.infrastructure.fetchers.chain import TextFetcher
from god_news.infrastructure.source_health import build_source_policies
from god_news.infrastructure.testing import (
    DeterministicSpeechSynthesizer,
    DeterministicTextGenerator,
    DeterministicVoiceProfileResolver,
    InMemoryMemoryProvider,
    InMemoryStoryRepository,
)
from god_news.sources.health import SourceHealthMonitor
from god_news.sources.registry import create_default_source_registry


@dataclass(slots=True)
class Stack:
    settings: Settings
    repository: InMemoryStoryRepository
    generator: DeterministicTextGenerator
    memory: InMemoryMemoryProvider
    synthesizer: DeterministicSpeechSynthesizer
    voice_resolver: DeterministicVoiceProfileResolver
    workflow: StoryWorkflow
    container: AppContainer


def _touch(path: Path, content: str = "fixture") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def stack(tmp_path: Path) -> Stack:
    vendor = tmp_path / "vendor"
    settings = Settings(
        _env_file=None,
        environment=Environment.TEST,
        output_dir=tmp_path / "outputs",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        deepseek_api_key=SecretStr("test-only"),
        gpt_sovits_root=vendor,
        gpt_sovits_python=_touch(vendor / "runtime" / "python.exe"),
        gpt_sovits_config=_touch(vendor / "GPT_SoVITS" / "configs" / "tts.yaml"),
        tts_reference_audio=_touch(vendor / "voices" / "ref.wav"),
        tts_reference_text_file=_touch(vendor / "voices" / "ref.txt", "reference"),
    )
    repository = InMemoryStoryRepository()
    generator = DeterministicTextGenerator()
    memory = InMemoryMemoryProvider()
    synthesizer = DeterministicSpeechSynthesizer(settings.output_dir)
    voice_resolver = DeterministicVoiceProfileResolver(vendor)
    fetcher = TextFetcher()
    coordinator = MemoryCoordinator(memory, recall_fail_open=True, recall_limit=5)
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
        memory=coordinator,
        synthesizer=synthesizer,
        source_normalizer=source_normalizers,
        voice_resolver=voice_resolver,
    )
    container = AppContainer(
        settings=settings,
        repository=repository,
        fetcher=fetcher,
        generator=generator,
        memory_provider=memory,
        synthesizer=synthesizer,
        workflow=workflow,
        source_normalizers=source_normalizers,
        source_health=source_health,
    )
    return Stack(
        settings=settings,
        repository=repository,
        generator=generator,
        memory=memory,
        synthesizer=synthesizer,
        voice_resolver=voice_resolver,
        workflow=workflow,
        container=container,
    )
