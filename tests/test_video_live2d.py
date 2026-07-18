from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import sys
import wave
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from god_news.domain.enums import SceneTransition, SpeechEmotion
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    ScriptDocument,
    ScriptSegment,
    SynthesisMetadata,
)
from god_news.domain.source_media import SourceVideoProbe
from god_news.domain.video import Live2DRenderDiagnostics
from god_news.infrastructure.video_live2d import LocalLive2DHostRenderer
from god_news.operations.models import RoleKind, RoleProfile, RoleVisualAssets
from god_news.video_errors import VideoNarrationSynthesisError

SHA = "0" * 64


def _load_worker_module() -> ModuleType:
    path = Path("scripts/render_live2d_host.py").resolve(strict=True)
    spec = importlib.util.spec_from_file_location("render_live2d_host_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Profiles:
    def __init__(self, profile: RoleProfile | None) -> None:
        self.profile = profile

    async def get_enabled_by_speaker_id(self, speaker_id: str) -> RoleProfile | None:
        if self.profile is not None and self.profile.speaker_id == speaker_id:
            return self.profile
        return None


class _Inspector:
    def __init__(self, duration_ms: int) -> None:
        self.duration_ms = duration_ms

    async def inspect(self, path: Path) -> SourceVideoProbe:
        assert await asyncio.to_thread(path.is_file)
        return SourceVideoProbe(
            duration_ms=self.duration_ms,
            width=720,
            height=720,
            video_codec="vp9",
            audio_codec=None,
            fps=30,
        )


def _script() -> ScriptDocument:
    return ScriptDocument(
        title="Good news",
        spoken_language="en-US",
        segments=[
            ScriptSegment(
                sequence=0,
                spoken_text="A small act of kindness travelled far.",
                spoken_language="en-US",
                captions=[],
                speaker_id="anchor",
                emotion=SpeechEmotion.HAPPINESS,
                scene_transition=SceneTransition.CROSSFADE,
                speed=1,
                pitch=0,
            )
        ],
    )


def _audio(script: ScriptDocument, path: Path) -> AudioBundle:
    path.write_bytes(b"RIFF-test-audio")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return AudioBundle(
        revision=script.revision,
        provider="fixture",
        model_identity="fixture",
        synthesis=SynthesisMetadata(
            seed=1,
            reference_audio_sha256=SHA,
            runtime_config_sha256=SHA,
            gpt_weights_sha256=SHA,
            sovits_weights_sha256=SHA,
            prompt_language="en-US",
            text_language="en-US",
        ),
        clips=[
            AudioClip(
                segment_id=script.segments[0].segment_id,
                path=str(path),
                duration_ms=1_200,
                sample_rate_hz=24_000,
                channels=1,
                sha256=digest,
            )
        ],
    )


def _model(root: Path) -> Path:
    model_dir = root / "anchor"
    model_dir.mkdir(parents=True)
    (model_dir / "anchor.moc").write_bytes(b"model-v1")
    (model_dir / "texture.png").write_bytes(b"texture-v1")
    (model_dir / "happy.mtn").write_bytes(b"motion-v1")
    model_path = model_dir / "3.model.json"
    model_path.write_text(
        json.dumps(
            {
                "model": "anchor.moc",
                "textures": ["texture.png"],
                "motions": {"happiness": [{"file": "happy.mtn"}]},
            }
        ),
        encoding="utf-8",
    )
    return model_path


def _renderer(
    *,
    tmp_path: Path,
    model_root: Path,
    profile: RoleProfile | None,
    duration_ms: int = 1_200,
) -> LocalLive2DHostRenderer:
    return LocalLive2DHostRenderer(
        profiles=_Profiles(profile),
        python_executable=sys.executable,
        worker_script=Path("scripts/render_live2d_host.py"),
        inspector=_Inspector(duration_ms),  # type: ignore[arg-type]
        output_root=tmp_path / "hosts",
        trusted_asset_roots=[model_root],
        timeout_seconds=5,
        max_parallel_segments=1,
        width=720,
        height=720,
        fps=30,
    )


@pytest.mark.asyncio
async def test_live2d_renderer_snapshots_role_model_audio_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_root = tmp_path / "models"
    model_path = _model(model_root)
    profile = RoleProfile(
        slug="main-anchor",
        display_name="Main anchor",
        kind=RoleKind.HOST,
        speaker_id="anchor",
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(model_path)),
    )
    script = _script()
    audio = _audio(script, tmp_path / "clip.wav")
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=profile)

    async def fake_worker(**kwargs: object) -> Live2DRenderDiagnostics:
        output_path = kwargs["output_path"]
        trace_path = kwargs["trace_path"]
        assert isinstance(output_path, Path)
        assert isinstance(trace_path, Path)
        output_path.write_bytes(b"transparent-vp9-fixture")
        trace_path.write_text('{"frame":0}\n', encoding="utf-8")
        trace_bytes = trace_path.read_bytes()
        return Live2DRenderDiagnostics.model_validate(
            _diagnostic_payload(
                trace_path=str(trace_path),
                trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
                trace_size_bytes=len(trace_bytes),
            )
        )

    monkeypatch.setattr(renderer, "_run_worker", fake_worker)
    result = await renderer.prepare(batch_id=uuid4(), script=script, audio=audio)

    assert result.renderer == "live2d_prerender"
    host = result.host_videos[0]
    assert host.segment_id == script.segments[0].segment_id
    assert host.speaker_id == "anchor"
    assert host.role_profile_id == profile.profile_id
    assert host.role_profile_version == profile.version
    assert host.audio_sha256 == audio.clips[0].sha256
    assert host.model_sha256 != SHA
    assert await asyncio.to_thread(Path(host.local_path).read_bytes) == b"transparent-vp9-fixture"
    assert host.sha256 == hashlib.sha256(b"transparent-vp9-fixture").hexdigest()
    assert host.diagnostics is not None
    trace_path = Path(host.diagnostics.trace_path)
    assert await asyncio.to_thread(trace_path.read_text, encoding="utf-8") == '{"frame":0}\n'
    trace_bytes = await asyncio.to_thread(trace_path.read_bytes)
    assert host.diagnostics.trace_sha256 == hashlib.sha256(trace_bytes).hexdigest()


@pytest.mark.asyncio
async def test_live2d_renderer_rejects_unconfigured_final_speaker(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    _model(model_root)
    script = _script()
    audio = _audio(script, tmp_path / "clip.wav")
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=None)

    with pytest.raises(VideoNarrationSynthesisError, match="no enabled Live2D"):
        await renderer.prepare(batch_id=uuid4(), script=script, audio=audio)


def test_live2d_renderer_rejects_model_outside_trusted_root(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    _model(model_root)
    outside = _model(tmp_path / "outside")
    profile = RoleProfile(
        slug="main-anchor",
        display_name="Main anchor",
        kind=RoleKind.HOST,
        speaker_id="anchor",
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(outside)),
    )
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=profile)

    with pytest.raises(VideoNarrationSynthesisError, match="trusted root"):
        renderer._resolve_model_path(str(outside))


def test_pcm_envelope_normalizes_unsigned_8_bit_silence(tmp_path: Path) -> None:
    worker = _load_worker_module()
    audio_path = tmp_path / "silence-8bit.wav"
    with wave.open(str(audio_path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(1)
        target.setframerate(8_000)
        target.writeframes(bytes([128]) * 8_000)

    envelope = worker._read_pcm_envelope(audio_path, fps=20, frame_count=20)

    assert envelope == [0.0] * 20


def test_mouth_envelope_uses_attack_and_slower_release() -> None:
    worker = _load_worker_module()

    envelope = worker._smooth_envelope(
        [0.0, 1.0, 1.0, 0.0, 0.0],
        fps=30,
        attack_ms=40,
        release_ms=160,
    )

    assert 0 < envelope[1] < envelope[2] < 1
    assert envelope[3] > 0
    assert envelope[3] - envelope[4] < envelope[2] - envelope[1]


def test_deterministic_blink_and_idle_pose_are_bounded() -> None:
    worker = _load_worker_module()

    blink_track = [worker._blink_openness(index, fps=30) for index in range(150)]
    assert min(blink_track) == 0
    assert max(blink_track) == 1
    assert blink_track == [
        worker._blink_openness(index, fps=30) for index in range(150)
    ]

    poses = [worker._idle_pose(index, fps=30, intensity=0.35) for index in range(150)]
    assert all(abs(pose["PARAM_ANGLE_X"]) <= 3.4 * 0.35 for pose in poses)
    assert any(
        not math.isclose(
            poses[index]["PARAM_EYE_BALL_X"],
            poses[index + 1]["PARAM_EYE_BALL_X"],
        )
        for index in range(len(poses) - 1)
    )


def test_capture_retries_transient_blank_without_advancing_state() -> None:
    worker = _load_worker_module()
    blank = bytes(4 * 4 * 4)
    visible = bytearray(blank)
    for offset in range(3, len(visible), 4):
        visible[offset] = 255
    attempts = iter((blank, bytes(visible)))

    pixels, capture_attempts = worker._capture_frame_with_retries(
        lambda: next(attempts),
        width=4,
        height=4,
        previous_alpha_area=1.0,
        max_attempts=3,
    )

    assert pixels == bytes(visible)
    assert capture_attempts == 2


def test_capture_fails_closed_after_persistent_blank_frames() -> None:
    worker = _load_worker_module()
    blank = bytes(4 * 4 * 4)
    captures = 0

    def capture() -> bytes:
        nonlocal captures
        captures += 1
        return blank

    with pytest.raises(RuntimeError, match=r"three consecutive|3 consecutive"):
        worker._capture_frame_with_retries(
            capture,
            width=4,
            height=4,
            previous_alpha_area=1.0,
            max_attempts=3,
        )

    assert captures == 3


def _diagnostic_payload(**overrides: object) -> dict[str, object]:
    metric = {
        "samples": 36,
        "duration_seconds": 1.2,
        "minimum": 0.0,
        "maximum": 0.9,
        "p95_absolute_value": 0.8,
        "p99_absolute_value": 0.88,
        "maximum_absolute_value": 0.9,
        "p95_absolute_step": 0.1,
        "p99_absolute_step": 0.15,
        "maximum_absolute_step": 0.2,
        "p95_absolute_velocity": 1.0,
        "maximum_absolute_velocity": 2.0,
        "p95_absolute_acceleration": 4.0,
        "maximum_absolute_acceleration": 8.0,
        "p95_absolute_jerk": 20.0,
        "maximum_absolute_jerk": 40.0,
        "direction_reversals_per_second": 1.0,
        "high_frequency_energy_ratio": 0.1,
        "alternating_energy_ratio": 0.02,
    }
    threshold = {
        "maximum_absolute_step": 0.35,
        "maximum_absolute_velocity": 7.7,
        "maximum_absolute_acceleration": 92.0,
        "maximum_absolute_jerk": 1080.0,
        "maximum_direction_reversals_per_second": 18.0,
        "maximum_high_frequency_energy_ratio": 1.1,
    }
    parameter_owners = {
        "PARAM_ANGLE_X": "motion_mixer",
        "PARAM_ANGLE_Y": "motion_mixer",
        "PARAM_ANGLE_Z": "motion_mixer",
        "PARAM_BODY_ANGLE_X": "motion_mixer",
        "PARAM_BREATH": "breath_controller",
        "PARAM_EYE_BALL_X": "eye_gaze_mixer",
        "PARAM_EYE_BALL_Y": "eye_gaze_mixer",
        "PARAM_EYE_L_OPEN": "blink_controller",
        "PARAM_EYE_R_OPEN": "blink_controller",
        "PARAM_MOUTH_OPEN_Y": "lip_sync_controller",
    }
    parameter_diagnostic = {
        "range": {"minimum": 0.0, "maximum": 1.0, "default": 0.0},
        "metrics": metric,
        "threshold": threshold,
        "findings": [],
    }
    payload: dict[str, object] = {
        "schema_version": "2.0",
        "control_mode": "final",
        "frames": 36,
        "envelope_frames": 36,
        "rendered_frames": 36,
        "fps": 30,
        "time_delta_ms_min": 33,
        "time_delta_ms_max": 34,
        "motion_group": "happiness",
        "motion_restarts": 1,
        "motion_state_counts": {"playing_motion": 36},
        "motion_switch_max_delta": 0.1,
        "motion_source_switch_max_delta": 0.4,
        "motion_metadata": {
            "file": "happy.mtn",
            "fps": 30,
            "fade_in_ms": 1_000,
            "fade_out_ms": 1_000,
            "frames": 36,
        },
        "expression": "happiness",
        "blink_events": 0,
        "mouth_min": 0.0,
        "mouth_p50": 0.2,
        "mouth_p95": 0.8,
        "mouth_max": 0.9,
        "mouth_max_delta": 0.2,
        "voiced_frame_ratio": 0.8,
        "exact_duplicate_pair_ratio": 0.02,
        "longest_exact_duplicate_run": 1,
        "controlled_parameters": list(parameter_owners),
        "parameter_owners": parameter_owners,
        "parameter_metrics": {
            parameter: parameter_diagnostic for parameter in parameter_owners
        },
        "image_metrics": {"perceptual_delta": metric},
        "image_thresholds": {"perceptual_delta_p99": 0.16},
        "gate_findings": [],
        "quality_gate_passed": True,
        "audio_calibration": {"noise_floor": 0.0015, "normalization_peak": 0.25},
        "trace_path": "trace.jsonl",
        "trace_sha256": hashlib.sha256(b"trace").hexdigest(),
        "trace_size_bytes": 5,
    }
    payload.update(overrides)
    return payload


def test_live2d_diagnostic_rejects_inconsistent_percentiles() -> None:
    with pytest.raises(ValidationError, match="mouth percentiles"):
        Live2DRenderDiagnostics.model_validate(
            _diagnostic_payload(mouth_p50=0.9, mouth_p95=0.4)
        )


def test_live2d_renderer_rejects_frozen_worker_diagnostic(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    model_path = _model(model_root)
    profile = RoleProfile(
        slug="main-anchor",
        display_name="Main anchor",
        kind=RoleKind.HOST,
        speaker_id="anchor",
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(model_path)),
    )
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=profile)
    payload = _diagnostic_payload(
        exact_duplicate_pair_ratio=0.75,
        longest_exact_duplicate_run=15,
    )

    with pytest.raises(VideoNarrationSynthesisError, match="duplicate frames"):
        renderer._validate_worker_diagnostics(
            json.dumps(payload).encode(),
            duration_ms=1_200,
        )


def test_live2d_renderer_rejects_failed_dynamic_gate(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    model_path = _model(model_root)
    profile = RoleProfile(
        slug="main-anchor",
        display_name="Main anchor",
        kind=RoleKind.HOST,
        speaker_id="anchor",
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(model_path)),
    )
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=profile)
    payload = _diagnostic_payload(
        quality_gate_passed=False,
        gate_findings=[
            {
                "code": "param_angle_x_maximum_absolute_jerk_exceeded",
                "metric": "maximum_absolute_jerk",
                "observed": 1_100.0,
                "threshold": 1_080.0,
            }
        ],
    )

    with pytest.raises(VideoNarrationSynthesisError, match="dynamic quality gate"):
        renderer._validate_worker_diagnostics(
            json.dumps(payload).encode(),
            duration_ms=1_200,
        )


def test_live2d_renderer_rejects_parameter_owner_conflict(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    model_path = _model(model_root)
    profile = RoleProfile(
        slug="main-anchor",
        display_name="Main anchor",
        kind=RoleKind.HOST,
        speaker_id="anchor",
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(model_path)),
    )
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=profile)
    owners = cast(dict[str, str], _diagnostic_payload()["parameter_owners"]).copy()
    owners["PARAM_EYE_L_OPEN"] = "motion_mixer"
    payload = _diagnostic_payload(parameter_owners=owners)

    with pytest.raises(VideoNarrationSynthesisError, match="ownership contract"):
        renderer._validate_worker_diagnostics(
            json.dumps(payload).encode(),
            duration_ms=1_200,
        )


def test_live2d_renderer_accepts_model_without_optional_parameters(tmp_path: Path) -> None:
    model_root = tmp_path / "models"
    model_path = _model(model_root)
    profile = RoleProfile(
        slug="main-anchor",
        display_name="Main anchor",
        kind=RoleKind.HOST,
        speaker_id="anchor",
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(model_path)),
    )
    renderer = _renderer(tmp_path=tmp_path, model_root=model_root, profile=profile)
    payload = _diagnostic_payload()
    controlled = cast(list[str], payload["controlled_parameters"])
    controlled.remove("PARAM_BREATH")
    cast(dict[str, str], payload["parameter_owners"]).pop("PARAM_BREATH")
    cast(dict[str, object], payload["parameter_metrics"]).pop("PARAM_BREATH")

    diagnostic = renderer._validate_worker_diagnostics(
        json.dumps(payload).encode(),
        duration_ms=1_200,
    )

    assert "PARAM_BREATH" not in diagnostic.controlled_parameters
