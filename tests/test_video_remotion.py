from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from anyio import Path as AsyncPath

from god_news.domain.enums import SpeechEmotion
from god_news.domain.models import ProductionManifest, TimelineSegment
from god_news.domain.video import (
    EpisodeHostVisibility,
    EpisodePlan,
    EpisodeScene,
    EpisodeSceneModule,
    RemotionVideoProps,
    VideoInputAsset,
    VideoInputAssetKind,
    VideoOutputProfileId,
)
from god_news.infrastructure.video_remotion import LocalRemotionBatchVideoRenderer
from god_news.video_errors import VideoRenderingError


def _props(audio_path: Path) -> RemotionVideoProps:
    story_id = uuid4()
    segment_id = uuid4()
    return RemotionVideoProps(
        manifest=ProductionManifest(
            story_id=story_id,
            script_revision=1,
            language="en",
            total_duration_ms=1_000,
            timeline=[
                TimelineSegment(
                    segment_id=segment_id,
                    sequence=0,
                    start_ms=0,
                    end_ms=1_000,
                    text="A verified local render fixture.",
                    speaker_id="narrator",
                    emotion=SpeechEmotion.HAPPINESS,
                    audio_path=str(audio_path),
                )
            ],
        ),
        title="Render fixture",
        intro_duration_ms=0,
        transition_duration_ms=0,
    )


def _input_assets(audio_path: Path) -> list[VideoInputAsset]:
    payload = audio_path.read_bytes()
    return [
        VideoInputAsset(
            kind=VideoInputAssetKind.AUDIO,
            local_path=str(audio_path.resolve()),
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )
    ]


def test_episode_scene_contract_rejects_invalid_renderer_capabilities() -> None:
    with pytest.raises(ValueError, match="visible host"):
        EpisodeScene(
            sequence=0,
            module_id=EpisodeSceneModule.HOST_EVIDENCE,
            narration_segment_id=uuid4(),
            speaker_id="narrator",
            host_visibility=EpisodeHostVisibility.HIDDEN,
        )


def test_remotion_props_reject_episode_plan_identity_drift(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    props = _props(audio)
    segment = props.manifest.timeline[0]
    plan = EpisodePlan(
        batch_id=props.manifest.story_id,
        scenes=[
            EpisodeScene(
                sequence=0,
                module_id=EpisodeSceneModule.HOST_EVIDENCE,
                narration_segment_id=segment.segment_id,
                speaker_id="different-speaker",
                host_visibility=EpisodeHostVisibility.VISIBLE,
                host_slot="primary",
                transition_type=segment.scene_transition,
            )
        ],
    )

    with pytest.raises(ValueError, match="speaker and transition"):
        props.model_copy(update={"episode_plan": plan}).model_validate(
            props.model_copy(update={"episode_plan": plan}).model_dump()
        )


@pytest.mark.asyncio
async def test_local_remotion_renderer_returns_both_verified_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "video"
    (package_dir / "node_modules" / "tsx" / "dist").mkdir(parents=True)
    (package_dir / "node_modules" / "tsx" / "dist" / "cli.mjs").touch()
    (package_dir / "scripts").mkdir()
    (package_dir / "scripts" / "render.ts").touch()
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-fixture")
    renderer = LocalRemotionBatchVideoRenderer(
        package_dir=package_dir,
        output_dir=tmp_path / "renders",
        node_command="node",
        timeout_seconds=30,
        max_parallel_batches=1,
        concurrency=1,
    )
    renderer._ffprobe = tmp_path / "ffprobe"  # type: ignore[assignment]

    async def fake_run(command: list[str], *, cwd: Path) -> str:
        assert cwd == package_dir
        if "--output" in command:
            output = Path(command[command.index("--output") + 1])
            profile_id = command[command.index("--profile") + 1]
            profile = next(
                item for item in _props(audio).output_profiles if item.profile_id == profile_id
            )
            await asyncio.to_thread(output.write_bytes, f"mp4-{profile_id}".encode())
            return json.dumps(
                {
                    "profile_id": profile_id,
                    "width": profile.width,
                    "height": profile.height,
                    "fps": profile.fps,
                    "duration_in_frames": 30,
                }
            )
        output = Path(command[-1])
        profile_id = output.stem
        profile = next(
            item for item in _props(audio).output_profiles if item.profile_id == profile_id
        )
        return json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": profile.width,
                        "height": profile.height,
                        "r_frame_rate": "30/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ]
            }
        )

    monkeypatch.setattr(renderer, "_run", fake_run)
    props = _props(audio)
    artifact = await renderer.render(
        props.manifest.story_id,
        props,
        _input_assets(audio),
    )

    assert {output.profile_id for output in artifact.outputs} == {
        VideoOutputProfileId.DOUYIN_VERTICAL,
        VideoOutputProfileId.BILIBILI_HORIZONTAL,
    }
    assert all([await AsyncPath(output.local_path).is_file() for output in artifact.outputs])
    assert all(output.video_codec == "h264" for output in artifact.outputs)
    assert all(output.audio_codec == "aac" for output in artifact.outputs)
    assert not any(
        path.name == "render-props.json"
        for path in (tmp_path / "renders").rglob("render-props.json")
    )


@pytest.mark.asyncio
async def test_local_remotion_renderer_removes_partial_attempt_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "video"
    (package_dir / "node_modules" / "tsx" / "dist").mkdir(parents=True)
    (package_dir / "node_modules" / "tsx" / "dist" / "cli.mjs").touch()
    (package_dir / "scripts").mkdir()
    (package_dir / "scripts" / "render.ts").touch()
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-fixture")
    renderer = LocalRemotionBatchVideoRenderer(
        package_dir=package_dir,
        output_dir=tmp_path / "renders",
        node_command="node",
        timeout_seconds=30,
        max_parallel_batches=1,
        concurrency=1,
    )
    renderer._ffprobe = tmp_path / "ffprobe"  # type: ignore[assignment]

    props = _props(audio)
    completed_profiles: list[str] = []

    async def fail_second_profile(command: list[str], *, cwd: Path) -> str:
        assert cwd == package_dir
        if "--output" in command:
            output = Path(command[command.index("--output") + 1])
            profile_id = command[command.index("--profile") + 1]
            if completed_profiles:
                raise VideoRenderingError("injected second-profile failure")
            completed_profiles.append(profile_id)
            profile = next(
                item for item in props.output_profiles if item.profile_id == profile_id
            )
            await asyncio.to_thread(output.write_bytes, b"first-profile-mp4")
            return json.dumps(
                {
                    "profile_id": profile_id,
                    "width": profile.width,
                    "height": profile.height,
                    "fps": profile.fps,
                    "duration_in_frames": 30,
                }
            )
        output = Path(command[-1])
        profile = next(
            item for item in props.output_profiles if item.profile_id.value == output.stem
        )
        return json.dumps(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": profile.width,
                        "height": profile.height,
                        "r_frame_rate": f"{profile.fps}/1",
                    },
                    {"codec_type": "audio", "codec_name": "aac"},
                ]
            }
        )

    monkeypatch.setattr(renderer, "_run", fail_second_profile)
    with pytest.raises(VideoRenderingError, match="second-profile"):
        await renderer.render(
            props.manifest.story_id,
            props,
            _input_assets(audio),
        )

    assert completed_profiles == [VideoOutputProfileId.DOUYIN_VERTICAL.value]
    batch_root = tmp_path / "renders" / str(props.manifest.story_id)
    assert not list(batch_root.glob("attempt-*"))


@pytest.mark.asyncio
async def test_local_remotion_renderer_rejects_changed_approved_input(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "video"
    (package_dir / "node_modules" / "tsx" / "dist").mkdir(parents=True)
    (package_dir / "node_modules" / "tsx" / "dist" / "cli.mjs").touch()
    (package_dir / "scripts").mkdir()
    (package_dir / "scripts" / "render.ts").touch()
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"approved-audio")
    assets = _input_assets(audio)
    audio.write_bytes(b"changed--audio")
    renderer = LocalRemotionBatchVideoRenderer(
        package_dir=package_dir,
        output_dir=tmp_path / "renders",
        node_command="node",
        timeout_seconds=30,
        max_parallel_batches=1,
        concurrency=1,
    )
    renderer._ffprobe = tmp_path / "ffprobe"  # type: ignore[assignment]
    props = _props(audio)

    with pytest.raises(VideoRenderingError, match="changed while its snapshot"):
        await renderer.render(props.manifest.story_id, props, assets)

    assert not list((tmp_path / "renders").rglob("attempt-*"))


@pytest.mark.asyncio
async def test_local_remotion_renderer_limits_parallel_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package_dir = tmp_path / "video"
    renderer = LocalRemotionBatchVideoRenderer(
        package_dir=package_dir,
        output_dir=tmp_path / "renders",
        node_command="node",
        timeout_seconds=30,
        max_parallel_batches=1,
        concurrency=1,
    )
    active = 0
    maximum = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def controlled_render(batch_id, props, input_assets):  # type: ignore[no-untyped-def]
        nonlocal active, maximum
        del batch_id, props, input_assets
        active += 1
        maximum = max(maximum, active)
        entered.set()
        await release.wait()
        active -= 1
        raise VideoRenderingError("stop fixture")

    monkeypatch.setattr(renderer, "_render_exclusive", controlled_render)
    props = _props(tmp_path / "unused.wav")
    first = asyncio.create_task(renderer.render(uuid4(), props, []))
    await entered.wait()
    second = asyncio.create_task(renderer.render(uuid4(), props, []))
    await asyncio.sleep(0)
    assert active == 1
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert maximum == 1
    assert all(isinstance(result, VideoRenderingError) for result in results)


@pytest.mark.asyncio
async def test_local_remotion_cleanup_removes_only_attempt_directories(tmp_path: Path) -> None:
    package_dir = tmp_path / "video"
    renderer = LocalRemotionBatchVideoRenderer(
        package_dir=package_dir,
        output_dir=tmp_path / "renders",
        node_command="node",
        timeout_seconds=30,
        max_parallel_batches=1,
        concurrency=1,
    )
    batch_root = tmp_path / "renders" / str(uuid4())
    (batch_root / "attempt-orphan").mkdir(parents=True)
    retained = batch_root / "retained.mp4"
    retained.write_bytes(b"complete")

    assert await renderer.cleanup_interrupted([UUID(batch_root.name)]) == 1
    assert not (batch_root / "attempt-orphan").exists()
    assert retained.is_file()


@pytest.mark.asyncio
async def test_local_remotion_rejects_linked_batch_root_without_deleting_target(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "video"
    (package_dir / "node_modules" / "tsx" / "dist").mkdir(parents=True)
    (package_dir / "node_modules" / "tsx" / "dist" / "cli.mjs").touch()
    (package_dir / "scripts").mkdir()
    (package_dir / "scripts" / "render.ts").touch()
    output_root = tmp_path / "renders"
    output_root.mkdir()
    batch_id = uuid4()
    external = tmp_path / "external"
    marker = external / "attempt-do-not-delete" / "marker.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("retained", encoding="utf-8")
    linked = output_root / str(batch_id)
    try:
        linked.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"directory symlinks are unavailable: {exc}")
        created = await asyncio.to_thread(
            subprocess.run,
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(external)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            pytest.skip(f"directory links are unavailable: {created.stderr}")

    renderer = LocalRemotionBatchVideoRenderer(
        package_dir=package_dir,
        output_dir=output_root,
        node_command="node",
        timeout_seconds=30,
        max_parallel_batches=1,
        concurrency=1,
    )
    renderer._ffprobe = tmp_path / "ffprobe"  # type: ignore[assignment]

    assert await renderer.cleanup_interrupted([batch_id]) == 0
    assert marker.read_text(encoding="utf-8") == "retained"
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"approved-audio")
    with pytest.raises(VideoRenderingError, match="safe local directory"):
        await renderer.render(batch_id, _props(audio), _input_assets(audio))
    assert marker.read_text(encoding="utf-8") == "retained"
    await asyncio.to_thread(os.rmdir, linked)
