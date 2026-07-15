from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from god_news.domain.enums import SceneTransition, SpeechEmotion
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    ScriptDocument,
    ScriptSegment,
    SynthesisMetadata,
)
from god_news.domain.source_media import SourceVideoProbe
from god_news.infrastructure.video_live2d import LocalLive2DHostRenderer
from god_news.operations.models import RoleKind, RoleProfile, RoleVisualAssets
from god_news.video_errors import VideoNarrationSynthesisError

SHA = "0" * 64


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

    async def fake_worker(**kwargs: object) -> None:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.write_bytes(b"transparent-vp9-fixture")

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
