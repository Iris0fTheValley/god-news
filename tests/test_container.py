from __future__ import annotations

from pathlib import Path

import pytest

from god_news.config import Environment, MemoryProviderName, Settings
from god_news.container import build_container


@pytest.mark.asyncio
async def test_production_composition_root_builds_without_external_calls(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        memory_provider=MemoryProviderName.CHROMADB,
        memory_chroma_persist_directory=tmp_path / "chroma",
        memory_chroma_collection="container-test-memory",
        browser_egress_isolated=True,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        output_dir=tmp_path / "outputs",
        deepseek_api_key="",
        tts_enabled=False,
        enable_drission_fetcher=True,
        enable_scrapy_fetcher=True,
    )
    container = await build_container(settings)
    try:
        report = await container.readiness()
        assert not report.ready
        assert "database:ok" in report.checks
        assert "llm:missing_api_key" in report.checks
        assert "memory:ok:chromadb" in report.checks
        assert "tts:disabled" in report.checks
        await container.repository.healthcheck()
    finally:
        await container.aclose()
