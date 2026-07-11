from __future__ import annotations

import wave
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from god_news.domain.models import ScriptDocument, ScriptSegment
from god_news.errors import ConfigurationError, TTSGenerationError
from god_news.infrastructure.tts.gpt_sovits import (
    GPTSoVITSSpeechSynthesizer,
    UnavailableSpeechSynthesizer,
    _choose_loopback_port,
    _inspect_wav,
    _prepare_runtime_config,
    _sha256_file,
    _within,
)


def test_runtime_config_selects_profile_without_vendor_fallback(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    gpt = root / "models" / "gpt.ckpt"
    sovits = root / "models" / "sovits.pth"
    bert = root / "models" / "bert"
    hubert = root / "models" / "hubert"
    for directory in (bert, hubert):
        directory.mkdir(parents=True)
    for weight in (gpt, sovits):
        weight.parent.mkdir(parents=True, exist_ok=True)
        weight.write_bytes(b"weights")
    source = root / "tts.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "v2Pro": {
                    "version": "v2Pro",
                    "t2s_weights_path": "models/gpt.ckpt",
                    "vits_weights_path": "models/sovits.pth",
                    "bert_base_path": "models/bert",
                    "cnhuhbert_base_path": "models/hubert",
                    "device": "cpu",
                    "is_half": False,
                }
            }
        ),
        encoding="utf-8",
    )
    destination = tmp_path / "runtime" / "tts.yaml"
    prepared = _prepare_runtime_config(
        source_path=source,
        destination_path=destination,
        root=root,
        profile_name="v2Pro",
        gpt_weights=None,
        sovits_weights=None,
        device="cuda",
        use_half_precision=True,
    )
    written = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert written["custom"]["version"] == "v2Pro"
    assert written["custom"]["device"] == "cuda"
    assert prepared.gpt_weights_path == gpt.resolve()
    assert prepared.sovits_weights_path == sovits.resolve()


def _make_synthesizer(tmp_path: Path) -> GPTSoVITSSpeechSynthesizer:
    root = tmp_path / "vendor"
    root.mkdir(parents=True)
    for path, content in (
        (root / "runtime" / "python.exe", b"runtime"),
        (root / "api_v2.py", b"# fixture"),
        (root / "models" / "gpt.ckpt", b"gpt weights"),
        (root / "models" / "sovits.pth", b"sovits weights"),
        (root / "reference.txt", b"reference transcript"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for directory in (root / "models" / "bert", root / "models" / "hubert"):
        directory.mkdir(parents=True)
    (root / "tts.yaml").write_text(
        yaml.safe_dump(
            {
                "v2Pro": {
                    "version": "v2Pro",
                    "t2s_weights_path": "models/gpt.ckpt",
                    "vits_weights_path": "models/sovits.pth",
                    "bert_base_path": "models/bert",
                    "cnhuhbert_base_path": "models/hubert",
                }
            }
        ),
        encoding="utf-8",
    )
    with wave.open(str(root / "reference.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\0\0" * 64_000)
    return GPTSoVITSSpeechSynthesizer(
        root=root,
        python_executable=root / "runtime" / "python.exe",
        source_config=root / "tts.yaml",
        output_dir=tmp_path / "output",
        reference_audio=root / "reference.wav",
        reference_text_file=root / "reference.txt",
        prompt_language="EN",
        text_language="AUTO",
        default_speaker_id="narrator",
        model_profile="v2Pro",
        gpt_weights=None,
        sovits_weights=None,
        device="cuda",
        use_half_precision=True,
        startup_timeout_seconds=1,
        request_timeout_seconds=1,
        shutdown_timeout_seconds=1,
        probe_timeout_seconds=1,
        startup_poll_interval_seconds=0.01,
        force_shutdown_wait_seconds=0.1,
        process_kill_grace_seconds=0.1,
        drain_timeout_seconds=0.1,
        max_audio_bytes=1024,
        seed=42,
        top_k=5,
        top_p=1.0,
        temperature=1.0,
        text_split_method="cut5",
        batch_size=1,
        batch_threshold=0.75,
        fragment_interval=0.3,
        repetition_penalty=1.35,
        parallel_infer=True,
    )


def _script(
    *, speaker_id: str = "narrator", emotion: str = "neutral", pitch: float = 0.0
) -> ScriptDocument:
    return ScriptDocument(
        title="Fixture",
        language="zh-CN",
        segments=[
            ScriptSegment(
                sequence=0,
                text="A deterministic TTS boundary fixture.",
                speaker_id=speaker_id,
                emotion=emotion,
                speed=1.0,
                pitch=pitch,
            )
        ],
    )


@pytest.mark.asyncio
async def test_tts_local_contracts_without_starting_the_model(tmp_path: Path) -> None:
    synthesizer = _make_synthesizer(tmp_path)
    synthesizer._validate_paths()
    await synthesizer.healthcheck()
    synthesizer._validate_capabilities(_script())
    assert synthesizer._prompt_language == "en"
    assert synthesizer._text_language == "auto"

    digest = await synthesizer._cached_file_hash(synthesizer._reference_audio)
    assert digest == _sha256_file(synthesizer._reference_audio)
    assert await synthesizer._cached_file_hash(synthesizer._reference_audio) == digest

    with pytest.raises(TTSGenerationError, match="speaker_id"):
        synthesizer._validate_capabilities(_script(speaker_id="guest"))
    with pytest.raises(TTSGenerationError, match="emotion"):
        synthesizer._validate_capabilities(_script(emotion="happy"))
    with pytest.raises(TTSGenerationError, match="pitch"):
        synthesizer._validate_capabilities(_script(pitch=1.0))
    await synthesizer.aclose()


def test_tts_wav_and_path_guards(tmp_path: Path) -> None:
    wav_path = tmp_path / "fixture.wav"
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\0\0" * 1_600)
    info = _inspect_wav(wav_path)
    assert (info.duration_ms, info.sample_rate_hz, info.channels) == (100, 16_000, 1)
    assert _within(wav_path, tmp_path)
    assert not _within(tmp_path / "missing.wav", tmp_path)
    assert 0 < _choose_loopback_port() < 65_536

    synthesizer = _make_synthesizer(tmp_path / "nested")
    synthesizer._reference_audio.unlink()
    with pytest.raises(ConfigurationError, match="incomplete"):
        synthesizer._validate_paths()


@pytest.mark.asyncio
async def test_unavailable_tts_is_an_explicit_domain_failure() -> None:
    synthesizer = UnavailableSpeechSynthesizer("TTS is intentionally disabled.")
    with pytest.raises(TTSGenerationError, match="intentionally disabled"):
        await synthesizer.synthesize(uuid4(), _script())
    await synthesizer.aclose()
