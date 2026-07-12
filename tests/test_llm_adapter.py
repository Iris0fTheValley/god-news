from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from god_news.config import LLMProvider
from god_news.errors import LLMGenerationError
from god_news.infrastructure.llm.openai_compatible import OpenAICompatibleTextGenerator


@pytest.mark.asyncio
async def test_deepseek_payload_disables_thinking_and_validates_json() -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "source_language": "en",
                            "translated_text": "译文",
                            "summary": "摘要",
                            "key_points": ["要点"],
                            "category": "kindness",
                            "secondary_categories": [],
                            "candidate_recommendation": True,
                            "classification_confidence": 0.91,
                            "classification_rationale": "A verified act of help.",
                            "risk_flags": [],
                        },
                        ensure_ascii=False,
                    )
                ),
            )
        ]
    )
    create = AsyncMock(return_value=completion)
    list_models = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(id="deepseek-v4-flash")])
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        models=SimpleNamespace(list=list_models),
        close=AsyncMock(),
    )
    generator = OpenAICompatibleTextGenerator(
        provider=LLMProvider.DEEPSEEK,
        api_key="test",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        timeout_seconds=5,
        max_retries=0,
        validation_retries=0,
        max_output_tokens=1024,
        temperature=0.1,
        max_source_characters=1000,
        max_memory_characters=100,
        thinking_enabled=False,
    )
    await generator._client.close()  # type: ignore[attr-defined]
    generator._client = fake_client  # type: ignore[assignment]
    await generator.healthcheck()
    result = await generator.translate_and_summarize(
        story_id=uuid4(),
        content="source",
        source_language="en",
        target_language="zh-CN",
        memories=[],
    )
    assert result.summary == "摘要"
    kwargs = create.await_args.kwargs
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
    assert kwargs["response_format"] == {"type": "json_object"}
    list_models.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_provider_uses_json_schema_and_retries_invalid_output() -> None:
    invalid = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="not-json"),
            )
        ]
    )
    valid = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "source_language": "en",
                            "translated_text": "translated",
                            "summary": "summary",
                            "key_points": ["point"],
                            "category": "forum",
                            "secondary_categories": [],
                            "candidate_recommendation": True,
                            "classification_confidence": 0.8,
                            "classification_rationale": "A forum account.",
                            "risk_flags": ["user_generated_content"],
                        }
                    )
                ),
            )
        ]
    )
    create = AsyncMock(side_effect=[invalid, valid])
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )
    generator = OpenAICompatibleTextGenerator(
        provider=LLMProvider.LOCAL,
        api_key="lm-studio",
        base_url="http://127.0.0.1:1234/v1",
        model="local-model",
        timeout_seconds=5,
        max_retries=0,
        validation_retries=1,
        max_output_tokens=1024,
        temperature=0.1,
        max_source_characters=1000,
        max_memory_characters=100,
        thinking_enabled=False,
    )
    await generator._client.close()  # type: ignore[attr-defined]
    generator._client = fake_client  # type: ignore[assignment]
    result = await generator.translate_and_summarize(
        story_id=uuid4(),
        content="source",
        source_language="en",
        target_language="zh-CN",
        memories=[],
    )
    assert result.target_language == "zh-CN"
    assert result.screening.category.value == "forum"
    assert create.await_count == 2
    response_format = create.await_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_source_limit_fails_explicitly_instead_of_truncating() -> None:
    generator = OpenAICompatibleTextGenerator(
        provider=LLMProvider.LOCAL,
        api_key="lm-studio",
        base_url="http://127.0.0.1:1234/v1",
        model="local-model",
        timeout_seconds=5,
        max_retries=0,
        validation_retries=0,
        max_output_tokens=1024,
        temperature=0.1,
        max_source_characters=10,
        max_memory_characters=100,
        thinking_enabled=False,
    )
    try:
        with pytest.raises(LLMGenerationError, match="input limit") as captured:
            await generator.translate_and_summarize(
                story_id=uuid4(),
                content="eleven chars",
                source_language="en",
                target_language="zh-CN",
                memories=[],
            )
        assert not captured.value.retryable
    finally:
        await generator.aclose()
