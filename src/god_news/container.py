from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from god_news.application.memory import MemoryCoordinator
from god_news.application.workflow import StoryWorkflow
from god_news.config import MemoryProviderName, Settings
from god_news.domain.models import HealthReport
from god_news.domain.ports import (
    Fetcher,
    MemoryProvider,
    SpeechSynthesizer,
    StoryRepository,
    TextGenerator,
)
from god_news.infrastructure.database import Database
from god_news.infrastructure.fetchers.chain import FetcherChain
from god_news.infrastructure.fetchers.drission import DrissionPageFetcher
from god_news.infrastructure.fetchers.jina import JinaReaderFetcher
from god_news.infrastructure.fetchers.scrapy import ScrapyTrafilaturaFetcher
from god_news.infrastructure.fetchers.url_policy import UrlPolicy
from god_news.infrastructure.llm.openai_compatible import (
    OpenAICompatibleTextGenerator,
    UnavailableTextGenerator,
)
from god_news.infrastructure.memory import ChromaDBMemoryProvider, NoopMemoryProvider
from god_news.infrastructure.repositories import SqlAlchemyStoryRepository
from god_news.infrastructure.source_health import (
    HttpSourceReachabilityProbe,
    build_source_policies,
)
from god_news.infrastructure.tts.gpt_sovits import (
    GPTSoVITSSpeechSynthesizer,
    UnavailableSpeechSynthesizer,
)
from god_news.sources.health import SourceHealthMonitor
from god_news.sources.registry import SourceNormalizerRegistry, create_default_source_registry


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    repository: StoryRepository
    fetcher: Fetcher
    generator: TextGenerator
    memory_provider: MemoryProvider
    synthesizer: SpeechSynthesizer
    workflow: StoryWorkflow
    source_normalizers: SourceNormalizerRegistry
    source_health: SourceHealthMonitor
    database: Database | None = None
    http_client: httpx.AsyncClient | None = None

    async def readiness(self) -> HealthReport:
        checks: list[str] = []
        ready = True
        try:
            await self.repository.healthcheck()
            checks.append("database:ok")
        except Exception:
            checks.append("database:error")
            ready = False

        if self.settings.active_llm_api_key is None:
            checks.append("llm:missing_api_key")
            ready = False
        else:
            try:
                await asyncio.wait_for(
                    self.generator.healthcheck(),
                    timeout=self.settings.readiness_timeout_seconds,
                )
                checks.append(f"llm:ok:{self.settings.llm_provider.value}")
            except Exception:
                checks.append(f"llm:error:{self.settings.llm_provider.value}")
                ready = False

        if self.settings.memory_provider is MemoryProviderName.NOOP:
            checks.append("memory:noop")
            if self.settings.environment.value == "production":
                ready = False
        else:
            try:
                await asyncio.wait_for(
                    self.memory_provider.healthcheck(),
                    timeout=self.settings.readiness_timeout_seconds,
                )
                checks.append("memory:ok:chromadb")
            except Exception:
                checks.append("memory:error:chromadb")
                ready = False

        if self.settings.enable_drission_fetcher and not self.settings.browser_egress_isolated:
            checks.append("fetcher:browser_egress_not_isolated")
            if self.settings.environment.value == "production":
                ready = False
        else:
            checks.append("fetcher:egress_policy_acknowledged")

        if not self.settings.tts_enabled:
            checks.append("tts:disabled")
            ready = False
        else:
            try:
                await asyncio.wait_for(
                    self.synthesizer.healthcheck(),
                    timeout=self.settings.readiness_timeout_seconds,
                )
                checks.append("tts:config_ok")
            except Exception:
                checks.append("tts:config_error")
                ready = False
        return HealthReport(ready=ready, checks=checks)

    async def aclose(self) -> None:
        await asyncio.gather(
            self.fetcher.aclose(),
            self.generator.aclose(),
            self.memory_provider.aclose(),
            self.synthesizer.aclose(),
            return_exceptions=True,
        )
        if self.http_client is not None:
            await self.http_client.aclose()
        if self.database is not None:
            await self.database.aclose()


async def build_container(settings: Settings) -> AppContainer:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    database = Database(
        settings.database_url,
        sqlite_busy_timeout_ms=settings.database_busy_timeout_ms,
    )
    if settings.database_auto_create:
        await database.create_schema()
    repository = SqlAlchemyStoryRepository(database.sessions)

    timeout = httpx.Timeout(
        connect=settings.fetch_connect_timeout_seconds,
        read=settings.fetch_read_timeout_seconds,
        write=settings.fetch_connect_timeout_seconds,
        pool=settings.fetch_connect_timeout_seconds,
    )
    http_client = httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=settings.fetch_max_connections,
            max_keepalive_connections=settings.fetch_max_keepalive_connections,
        ),
        follow_redirects=False,
        trust_env=False,
    )
    policy = UrlPolicy(
        allow_private=settings.allow_private_source_urls,
        allowed_ports=settings.allowed_source_ports,
    )
    url_fetchers: list[Fetcher] = [
        JinaReaderFetcher(
            client=http_client,
            policy=policy,
            base_url=settings.jina_base_url,
            api_key=(settings.jina_api_key.get_secret_value() if settings.jina_api_key else None),
            page_timeout_seconds=settings.jina_page_timeout_seconds,
            max_response_bytes=settings.fetch_max_response_bytes,
            min_content_characters=settings.fetch_min_content_characters,
        )
    ]
    if settings.enable_drission_fetcher:
        url_fetchers.append(
            DrissionPageFetcher(
                policy=policy,
                timeout_seconds=settings.drission_timeout_seconds,
                base_timeout_seconds=settings.drission_base_timeout_seconds,
                script_timeout_seconds=settings.drission_script_timeout_seconds,
                quit_timeout_seconds=settings.drission_quit_timeout_seconds,
                max_concurrency=settings.drission_max_concurrency,
                worker_module=settings.drission_worker_module,
                max_response_bytes=settings.fetch_max_response_bytes,
                min_content_characters=settings.fetch_min_content_characters,
            )
        )
    if settings.enable_scrapy_fetcher:
        url_fetchers.append(
            ScrapyTrafilaturaFetcher(
                policy=policy,
                timeout_seconds=settings.scrapy_timeout_seconds,
                worker_module=settings.scrapy_worker_module,
                max_response_bytes=settings.fetch_max_response_bytes,
                min_content_characters=settings.fetch_min_content_characters,
                download_timeout_seconds=settings.scrapy_download_timeout_seconds,
                redirect_max_times=settings.scrapy_redirect_max_times,
                retry_times=settings.scrapy_retry_times,
                depth_limit=settings.scrapy_depth_limit,
                close_page_count=settings.scrapy_close_page_count,
                user_agent=settings.scrapy_user_agent,
            )
        )
    fetcher = FetcherChain(url_fetchers)
    source_normalizers = create_default_source_registry()
    source_health = SourceHealthMonitor(
        normalizers=source_normalizers,
        policies=build_source_policies(settings),
        probe=HttpSourceReachabilityProbe(http_client),
    )

    api_key = settings.active_llm_api_key
    if api_key is None:
        generator: TextGenerator = UnavailableTextGenerator(
            "The selected LLM provider has no configured API key."
        )
    else:
        generator = OpenAICompatibleTextGenerator(
            provider=settings.llm_provider,
            api_key=api_key.get_secret_value(),
            base_url=settings.active_llm_base_url,
            model=settings.active_llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            validation_retries=settings.llm_validation_retries,
            max_output_tokens=settings.llm_max_output_tokens,
            temperature=settings.llm_temperature,
            max_source_characters=settings.max_source_characters,
            max_memory_characters=settings.memory_max_context_characters,
            thinking_enabled=settings.llm_thinking_enabled,
        )

    if settings.memory_provider is MemoryProviderName.NOOP:
        memory_provider: MemoryProvider = NoopMemoryProvider()
    else:
        memory_provider = ChromaDBMemoryProvider(
            persist_directory=settings.memory_chroma_persist_directory,
            collection_name=settings.memory_chroma_collection,
            embedding_function_name=settings.memory_chroma_embedding_function.value,
            embedding_model_name=settings.memory_chroma_embedding_model.value,
        )
    memory = MemoryCoordinator(
        memory_provider,
        recall_fail_open=settings.memory_recall_fail_open,
        recall_limit=settings.memory_recall_limit,
    )

    if settings.tts_enabled:
        synthesizer: SpeechSynthesizer = GPTSoVITSSpeechSynthesizer(
            root=settings.gpt_sovits_root,
            python_executable=settings.gpt_sovits_python,
            source_config=settings.gpt_sovits_config,
            output_dir=settings.output_dir,
            reference_audio=settings.tts_reference_audio,
            reference_text_file=settings.tts_reference_text_file,
            prompt_language=settings.tts_prompt_language,
            text_language=settings.tts_text_language,
            default_speaker_id=settings.tts_default_speaker_id,
            model_profile=settings.tts_model_profile,
            gpt_weights=settings.tts_gpt_weights,
            sovits_weights=settings.tts_sovits_weights,
            device=settings.tts_device,
            use_half_precision=settings.tts_use_half_precision,
            startup_timeout_seconds=settings.tts_startup_timeout_seconds,
            request_timeout_seconds=settings.tts_request_timeout_seconds,
            shutdown_timeout_seconds=settings.tts_shutdown_timeout_seconds,
            probe_timeout_seconds=settings.tts_probe_timeout_seconds,
            startup_poll_interval_seconds=settings.tts_startup_poll_interval_seconds,
            force_shutdown_wait_seconds=settings.tts_force_shutdown_wait_seconds,
            process_kill_grace_seconds=settings.tts_process_kill_grace_seconds,
            drain_timeout_seconds=settings.tts_drain_timeout_seconds,
            max_audio_bytes=settings.tts_max_audio_bytes,
            seed=settings.tts_seed,
            top_k=settings.tts_top_k,
            top_p=settings.tts_top_p,
            temperature=settings.tts_temperature,
            text_split_method=settings.tts_text_split_method,
            batch_size=settings.tts_batch_size,
            batch_threshold=settings.tts_batch_threshold,
            fragment_interval=settings.tts_fragment_interval,
            repetition_penalty=settings.tts_repetition_penalty,
            parallel_infer=settings.tts_parallel_infer,
            max_concurrency=settings.tts_max_concurrency,
        )
    else:
        synthesizer = UnavailableSpeechSynthesizer("Local TTS is disabled by configuration.")

    workflow = StoryWorkflow(
        repository=repository,
        fetcher=fetcher,
        generator=generator,
        memory=memory,
        synthesizer=synthesizer,
        source_normalizer=source_normalizers,
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
        database=database,
        http_client=http_client,
    )
