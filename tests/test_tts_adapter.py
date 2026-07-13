from __future__ import annotations

import io
import json
import os
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
import yaml

from god_news.domain.enums import SpeechEmotion
from god_news.domain.models import AudioClip, ScriptDocument, ScriptSegment
from god_news.errors import ConfigurationError, TTSGenerationError
from god_news.infrastructure.tts.dsakiko import (
    load_dsakiko_emotion_refs,
    load_dsakiko_voice_assets,
)
from god_news.infrastructure.tts.gpt_sovits import (
    GPTSoVITSSpeechSynthesizer,
    UnavailableSpeechSynthesizer,
    _ActiveRuntime,
    _choose_loopback_port,
    _FileSnapshot,
    _inspect_wav,
    _prepare_runtime_config,
    _PreparedConfig,
    _SegmentVoicePlan,
    _sha256_file,
    _VoiceRuntime,
    _within,
)
from god_news.voice_profiles import ResolvedVoiceProfile, VoiceReference


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

    # Speaker resolution and concrete emotion-reference selection now happen
    # asynchronously, after static capability checks. Non-neutral labels are
    # valid GPT-SoVITS reference selectors rather than a hard rejection.
    synthesizer._validate_capabilities(_script(speaker_id="guest", emotion="happiness"))
    with pytest.raises(TTSGenerationError, match="speaker_id"):
        await synthesizer._resolve_segment_voice_plans(_script(speaker_id="guest"))
    assert (await synthesizer._resolve_segment_voice_plans(_script(emotion="sadness")))[
        0
    ].emotion is SpeechEmotion.SADNESS
    with pytest.raises(TTSGenerationError, match="pitch"):
        synthesizer._validate_capabilities(_script(pitch=1.0))
    await synthesizer.aclose()


@pytest.mark.asyncio
async def test_tts_asset_hashes_are_metadata_aware_and_fail_closed(tmp_path: Path) -> None:
    synthesizer = _make_synthesizer(tmp_path)
    asset = synthesizer._root / "models" / "mutable-reference.wav"
    asset.write_bytes(b"first version")

    first = await synthesizer._snapshot_file(asset, label="test asset")
    asset.write_bytes(b"secondversion")  # Same byte count; mtime normally changes.
    assert await synthesizer._cached_file_hash(asset) != first.sha256

    # Even a pathological replacement that preserves size and mtime must not
    # reuse provenance after an explicit content verification boundary.
    stable = await synthesizer._snapshot_file(asset, label="test asset")
    stat = asset.stat()
    asset.write_bytes(b"third version")
    os.utime(asset, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ConfigurationError, match="changed during active"):
        await synthesizer._assert_snapshot_unchanged(
            stable,
            label="test asset",
            verify_content=True,
        )
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
    with pytest.raises(ConfigurationError, match="legacy reference audio"):
        synthesizer._validate_paths()


class _StaticVoiceResolver:
    def __init__(self, profiles: dict[str, ResolvedVoiceProfile]) -> None:
        self._profiles = profiles
        self.calls: list[str] = []

    async def resolve_voice(self, speaker_id: str) -> ResolvedVoiceProfile | None:
        self.calls.append(speaker_id)
        return self._profiles.get(speaker_id)


def _copy_reference_audio(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


@pytest.mark.asyncio
async def test_tts_resolves_role_emotion_references_once_per_speaker(tmp_path: Path) -> None:
    synthesizer = _make_synthesizer(tmp_path)
    sadness_audio = _copy_reference_audio(
        synthesizer._reference_audio,
        synthesizer._root / "references" / "sadness.wav",
    )
    refs = {
        emotion: VoiceReference(
            audio_path=(
                sadness_audio
                if emotion is SpeechEmotion.SADNESS
                else synthesizer._reference_audio
            ),
            text=f"{emotion.value} reference transcript",
        )
        for emotion in SpeechEmotion
    }
    profile = ResolvedVoiceProfile(
        profile_id=uuid4(),
        speaker_id="guest",
        model_profile="v2Pro",
        gpt_weights_path=synthesizer._root / "models" / "gpt.ckpt",
        sovits_weights_path=synthesizer._root / "models" / "sovits.pth",
        emotion_refs=refs,
        default_emotion=SpeechEmotion.HAPPINESS,
        reference_language="all_ja",
    )
    resolver = _StaticVoiceResolver({"guest": profile})
    synthesizer._voice_resolver = resolver
    script = ScriptDocument(
        title="Multi-emotion fixture",
        language="zh-CN",
        segments=[
            ScriptSegment(
                sequence=0,
                text="Happy segment.",
                speaker_id="guest",
                emotion=SpeechEmotion.HAPPINESS,
                speed=1.0,
                pitch=0.0,
            ),
            ScriptSegment(
                sequence=1,
                text="Sad segment.",
                speaker_id="guest",
                emotion=SpeechEmotion.SADNESS,
                speed=1.0,
                pitch=0.0,
            ),
        ],
    )

    plans = await synthesizer._resolve_segment_voice_plans(script)

    assert resolver.calls == ["guest"]
    assert plans[0].runtime == plans[1].runtime
    assert plans[0].reference_audio_path == synthesizer._reference_audio
    assert plans[0].reference_text == "happiness reference transcript"
    assert plans[1].reference_audio_path == sadness_audio.resolve()
    assert plans[1].reference_text == "sadness reference transcript"
    assert [plan.prompt_language for plan in plans] == ["all_ja", "all_ja"]


@pytest.mark.asyncio
async def test_tts_rejects_profile_references_outside_trusted_roots(tmp_path: Path) -> None:
    synthesizer = _make_synthesizer(tmp_path)
    outside_audio = _copy_reference_audio(
        synthesizer._reference_audio,
        tmp_path / "outside-trusted-root" / "reference.wav",
    )
    profile = ResolvedVoiceProfile(
        profile_id=uuid4(),
        speaker_id="guest",
        model_profile="v2Pro",
        gpt_weights_path=synthesizer._root / "models" / "gpt.ckpt",
        sovits_weights_path=synthesizer._root / "models" / "sovits.pth",
        emotion_refs={
            emotion: VoiceReference(
                audio_path=outside_audio,
                text=f"{emotion.value} reference transcript",
            )
            for emotion in SpeechEmotion
        },
        default_emotion=SpeechEmotion.HAPPINESS,
    )
    synthesizer._voice_resolver = _StaticVoiceResolver({"guest": profile})

    with pytest.raises(ConfigurationError, match="outside trusted local voice roots"):
        await synthesizer._resolve_segment_voice_plans(_script(speaker_id="guest"))


class _MockTTSResponse:
    def __init__(self, payload: bytes) -> None:
        self.status_code = 200
        self.headers = {"content-length": str(len(payload))}
        self._payload = payload

    async def __aenter__(self) -> _MockTTSResponse:
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback

    async def aiter_bytes(self):  # type: ignore[no-untyped-def]
        midpoint = max(1, len(self._payload) // 2)
        yield self._payload[:midpoint]
        yield self._payload[midpoint:]


class _MockTTSClient:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.requests: list[dict[str, Any]] = []

    def stream(self, method: str, url: str, *, json: dict[str, Any]) -> _MockTTSResponse:
        assert method == "POST"
        assert url.endswith("/tts")
        self.requests.append(json)
        return _MockTTSResponse(self._payload)


def _response_wav_bytes() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\0\0" * 1_600)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_tts_request_switches_reference_audio_and_prompt_per_segment(tmp_path: Path) -> None:
    synthesizer = _make_synthesizer(tmp_path)
    synthesizer._max_audio_bytes = 100_000
    sadness_audio = _copy_reference_audio(
        synthesizer._reference_audio,
        synthesizer._root / "references" / "sadness.wav",
    )
    client = _MockTTSClient(_response_wav_bytes())
    story_dir = synthesizer._output_dir / "story"
    story_dir.mkdir(parents=True)
    server = cast(Any, SimpleNamespace(port=18_001, force_shutdown=False))
    first = ScriptSegment(
        sequence=0,
        text="First emotion.",
        speaker_id="guest",
        emotion=SpeechEmotion.HAPPINESS,
        speed=1.0,
        pitch=0.0,
    )
    second = ScriptSegment(
        sequence=1,
        text="Second emotion.",
        speaker_id="guest",
        emotion=SpeechEmotion.SADNESS,
        speed=1.0,
        pitch=0.0,
    )

    first_clip = await synthesizer._generate_clip(
        client=cast(Any, client),
        server=server,
        segment=first,
        story_dir=story_dir,
        reference_audio_path=synthesizer._reference_audio,
        reference_text="happy reference",
        prompt_language="all_ja",
    )
    second_clip = await synthesizer._generate_clip(
        client=cast(Any, client),
        server=server,
        segment=second,
        story_dir=story_dir,
        reference_audio_path=sadness_audio,
        reference_text="sad reference",
        prompt_language="en",
    )

    assert first_clip.segment_id == first.segment_id
    assert second_clip.segment_id == second.segment_id
    assert [request["ref_audio_path"] for request in client.requests] == [
        str(synthesizer._reference_audio),
        str(sadness_audio),
    ]
    assert [request["prompt_text"] for request in client.requests] == [
        "happy reference",
        "sad reference",
    ]
    assert [request["prompt_lang"] for request in client.requests] == ["all_ja", "en"]


@pytest.mark.asyncio
async def test_tts_never_keeps_multiple_weight_runtimes_resident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synthesizer = _make_synthesizer(tmp_path)
    second_gpt = synthesizer._root / "models" / "other-gpt.ckpt"
    second_sovits = synthesizer._root / "models" / "other-sovits.pth"
    second_gpt.write_bytes(b"other gpt")
    second_sovits.write_bytes(b"other sovits")
    first_runtime = _VoiceRuntime(
        model_profile="v2Pro",
        gpt_weights_path=synthesizer._root / "models" / "gpt.ckpt",
        sovits_weights_path=synthesizer._root / "models" / "sovits.pth",
    )
    second_runtime = _VoiceRuntime(
        model_profile="v2Pro",
        gpt_weights_path=second_gpt,
        sovits_weights_path=second_sovits,
    )
    segments = [
        ScriptSegment(
            sequence=index,
            text=f"Segment {index}",
            speaker_id="guest",
            emotion=SpeechEmotion.HAPPINESS,
            speed=1.0,
            pitch=0.0,
        )
        for index in range(3)
    ]
    plans = [
        _SegmentVoicePlan(
            segment=segment,
            runtime=runtime,
            emotion=SpeechEmotion.HAPPINESS,
            reference_audio_path=synthesizer._reference_audio,
            reference_text="reference",
            prompt_language="en",
        )
        for segment, runtime in zip(
            segments,
            (first_runtime, second_runtime, first_runtime),
            strict=True,
        )
    ]
    live: set[str] = set()
    events: list[str] = []

    async def fake_start(runtime: _VoiceRuntime, _: Path) -> _ActiveRuntime:
        key = runtime.gpt_weights_path.name if runtime.gpt_weights_path is not None else "legacy"
        assert not live
        live.add(key)
        events.append(f"start:{key}")
        return _ActiveRuntime(
            server=cast(Any, SimpleNamespace(runtime_key=key)),
            prepared=_PreparedConfig(
                model_identity=f"gpt-sovits:{key}",
                gpt_weights_path=runtime.gpt_weights_path or synthesizer._reference_audio,
                sovits_weights_path=runtime.sovits_weights_path or synthesizer._reference_audio,
            ),
            runtime_config_sha256="a" * 64,
            gpt_weights_sha256="b" * 64,
            sovits_weights_sha256="c" * 64,
            gpt_weights_snapshot=_FileSnapshot(
                path=runtime.gpt_weights_path or synthesizer._reference_audio,
                size_bytes=0,
                modified_ns=0,
                sha256="b" * 64,
            ),
            sovits_weights_snapshot=_FileSnapshot(
                path=runtime.sovits_weights_path or synthesizer._reference_audio,
                size_bytes=0,
                modified_ns=0,
                sha256="c" * 64,
            ),
        )

    async def fake_stop(server: Any) -> None:
        live.remove(server.runtime_key)
        events.append(f"stop:{server.runtime_key}")

    async def fake_generate_clip(**kwargs: Any) -> AudioClip:
        segment = cast(ScriptSegment, kwargs["segment"])
        return AudioClip(
            segment_id=segment.segment_id,
            path=f"{segment.sequence}.wav",
            duration_ms=100,
            sample_rate_hz=16_000,
            channels=1,
            sha256="d" * 64,
        )

    monkeypatch.setattr(synthesizer, "_start_runtime", fake_start)
    monkeypatch.setattr(synthesizer, "_stop_server", fake_stop)
    monkeypatch.setattr(synthesizer, "_generate_clip", fake_generate_clip)

    async def fake_assert_snapshot_unchanged(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(synthesizer, "_assert_snapshot_unchanged", fake_assert_snapshot_unchanged)

    clips, provenance, _ = await synthesizer._generate_clips(
        plans=plans,
        story_dir=synthesizer._output_dir / "story",
        temp_dir=synthesizer._output_dir / "runtime",
    )

    assert not live
    assert events == [
        "start:gpt.ckpt",
        "stop:gpt.ckpt",
        "start:other-gpt.ckpt",
        "stop:other-gpt.ckpt",
        "start:gpt.ckpt",
        "stop:gpt.ckpt",
    ]
    assert [clip.segment_id for clip in clips] == [segment.segment_id for segment in segments]
    assert [entry.segment_id for entry in provenance] == [
        segment.segment_id for segment in segments
    ]


def test_dsakiko_reference_json_maps_paths_without_copying_assets(tmp_path: Path) -> None:
    root = tmp_path / "dsakiko"
    audio = root / "reference_audio" / "anon" / "reference.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\0\0" * 64_000)
    config = audio.parent / "reference_audio_and_text.json"
    config.write_text(
        json.dumps(
            {
                "emotion_refs": {
                    emotion.value: {
                        "audio_path": "../reference_audio\\anon\\reference.wav",
                        "text": f"{emotion.value} text",
                    }
                    for emotion in SpeechEmotion
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "GPT_SoVITS").mkdir()

    refs = load_dsakiko_emotion_refs(config_path=config, dsakiko_root=root)

    assert set(refs) == set(SpeechEmotion)
    assert refs[SpeechEmotion.SURPRISE].audio_path == str(audio.resolve())
    assert refs[SpeechEmotion.SURPRISE].text == "surprise text"


def test_dsakiko_voice_assets_preserve_reference_language(tmp_path: Path) -> None:
    root = tmp_path / "dsakiko"
    audio = root / "reference_audio" / "anon" / "reference.wav"
    audio.parent.mkdir(parents=True)
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16_000)
        handle.writeframes(b"\0\0" * 64_000)
    config = audio.parent / "reference_audio_and_text.json"
    config.write_text(
        json.dumps(
            {
                "emotion_refs": {
                    emotion.value: {
                        "audio_path": "../reference_audio\\anon\\reference.wav",
                        "text": f"{emotion.value} text",
                    }
                    for emotion in SpeechEmotion
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (audio.parent / "reference_audio_language.txt").write_text("3\n", encoding="utf-8")
    (root / "GPT_SoVITS").mkdir()

    assets = load_dsakiko_voice_assets(config_path=config, dsakiko_root=root)

    assert assets.reference_language == "all_ja"
    assert assets.emotion_refs[SpeechEmotion.HAPPINESS].audio_path == str(audio.resolve())


@pytest.mark.asyncio
async def test_unavailable_tts_is_an_explicit_domain_failure() -> None:
    synthesizer = UnavailableSpeechSynthesizer("TTS is intentionally disabled.")
    with pytest.raises(TTSGenerationError, match="intentionally disabled"):
        await synthesizer.synthesize(uuid4(), _script())
    await synthesizer.aclose()
