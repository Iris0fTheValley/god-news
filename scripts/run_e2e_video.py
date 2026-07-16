from __future__ import annotations

import argparse
import asyncio
import colorsys
import hashlib
import json
import os
import shutil
import struct
import sys
import wave
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from god_news.application.video_batches import VideoBatchService
from god_news.config import Settings, get_settings
from god_news.container import AppContainer, build_container
from god_news.domain.enums import (
    CaptionKind,
    ContentCategory,
    SceneTransition,
    SpeechEmotion,
    StoryStatus,
)
from god_news.domain.models import (
    AudioBundle,
    AudioClip,
    CaptionVariant,
    EditorialScreening,
    FetchedDocument,
    ProductionManifest,
    ScriptDocument,
    ScriptPreferences,
    ScriptSegment,
    SourceSnapshot,
    Story,
    SynthesisMetadata,
    TextSource,
    TimelineSegment,
    TranslationResult,
    utc_now,
)
from god_news.domain.source_transcription import (
    TimedCaptionCue,
    TranscriptReview,
    TranscriptReviewDecision,
)
from god_news.domain.video import (
    CreateVideoBatch,
    DirectedProgramDraft,
    EpisodeSceneModule,
    NarrationReviewDecision,
    ProgramDirectorPlan,
    SourceVideoAudioMode,
    SourceVideoPlacement,
    SourceVideoRenderAsset,
    SubmitNarrationReview,
    SubmitTimelineReview,
    SynthesizeBatchNarration,
    TimelineReviewDecision,
    VideoBatch,
    VideoBatchStory,
    VideoRenderArtifact,
)
from god_news.domain.video_ports import ProgramDirector
from god_news.infrastructure.llm.openai_compatible import (
    OpenAICompatibleProgramDirector,
    OpenAICompatibleTextGenerator,
)
from god_news.infrastructure.source_media_probe import FFprobeSourceVideoInspector
from god_news.infrastructure.tts.dsakiko import load_dsakiko_voice_assets
from god_news.infrastructure.video_assets import LocalBgmCatalog
from god_news.infrastructure.video_live2d import LocalLive2DHostRenderer
from god_news.infrastructure.video_remotion import LocalRemotionBatchVideoRenderer
from god_news.infrastructure.video_repository import SqlAlchemyVideoBatchRepository
from god_news.operations.models import (
    RoleKind,
    RoleProfile,
    RoleProfileCreate,
    RoleVisualAssets,
)
from god_news.video_errors import VideoRenderingError

WORKSPACE = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class DemoStorySpec:
    title: str
    original_text: str
    spoken_text: str
    caption_text: str
    source_captions: tuple[tuple[str, str], ...]
    category: ContentCategory
    hue: int
    tone_hz: int


DEMO_STORIES: tuple[DemoStorySpec, ...] = (
    DemoStorySpec(
        title="Books returned to a mountain library",
        original_text=(
            "A self-authored demonstration story about volunteers delivering donated books "
            "to a small mountain library."
        ),
        spoken_text="山あいの図書館に、町のみんなから新しい本が届けられました。",
        caption_text="镇上的人们把一批新书送到了山间的小图书馆。",
        source_captions=(
            ("Volunteers sort donated books.", "志愿者们整理捐赠图书。"),
            ("The boxes travel to the mountain library.", "书箱被送往山间图书馆。"),
            ("Children open a new reading corner.", "孩子们迎来了新的阅读角。"),
        ),
        category=ContentCategory.KINDNESS,
        hue=25,
        tone_hz=330,
    ),
    DemoStorySpec(
        title="A rescued turtle returns to the sea",
        original_text=(
            "A self-authored demonstration story about a rehabilitation team returning a "
            "healthy sea turtle to the ocean."
        ),
        spoken_text="けがを治したウミガメが、見守る人たちの前で海へ帰りました。",
        caption_text="康复后的海龟在人们的注视下重新回到了大海。",
        source_captions=(
            ("The rehabilitation team completes its final check.", "救助团队完成最后检查。"),
            ("A clear path is opened across the sand.", "沙滩上为海龟让出了一条通道。"),
            ("The turtle reaches the water on its own.", "海龟靠自己的力量回到海中。"),
        ),
        category=ContentCategory.CATS_DOGS,
        hue=95,
        tone_hz=392,
    ),
    DemoStorySpec(
        title="Students power their classroom with sunlight",
        original_text=(
            "A self-authored demonstration story about students and teachers installing a "
            "small solar system for a classroom."
        ),
        spoken_text="生徒と先生が力を合わせ、教室に小さな太陽光設備を完成させました。",
        caption_text="学生和老师一起为教室建成了一套小型太阳能设备。",
        source_captions=(
            ("Students measure the roof together.", "学生们一起测量屋顶。"),
            ("Teachers explain how the panels work.", "老师讲解太阳能板的工作原理。"),
            ("The classroom lights turn on with stored energy.", "教室用储存的能量点亮了灯。"),
        ),
        category=ContentCategory.KINDNESS,
        hue=155,
        tone_hz=440,
    ),
    DemoStorySpec(
        title="A community fridge stays full",
        original_text=(
            "A self-authored demonstration story about neighbors keeping a community fridge "
            "stocked with fresh food."
        ),
        spoken_text="地域の冷蔵庫には、近所の人たちが毎日少しずつ食べ物を届けています。",
        caption_text="邻居们每天都会为社区冰箱补上一点新鲜食物。",
        source_captions=(
            ("Neighbors label fresh donations.", "邻居们为新鲜捐赠食品贴上标签。"),
            ("Volunteers check dates and temperatures.", "志愿者检查日期和温度。"),
            ("Anyone who needs food may take it freely.", "有需要的人都可以自由取用。"),
        ),
        category=ContentCategory.FORUM,
        hue=215,
        tone_hz=494,
    ),
    DemoStorySpec(
        title="A lost dog finds its family again",
        original_text=(
            "A self-authored demonstration story about residents helping a lost dog return "
            "to its family."
        ),
        spoken_text="迷子になった犬は、町の人たちの連絡で無事に家族のもとへ戻りました。",
        caption_text="全镇居民接力提供帮助。走失的小狗平安回到了家人身边。",
        source_captions=(
            ("A resident shares a clear photo.", "一位居民分享了清晰的照片。"),
            ("Local shops help spread the notice.", "附近商店一起转发寻主信息。"),
            ("The family arrives for a quiet reunion.", "家人赶来。小狗与他们温柔重逢。"),
        ),
        category=ContentCategory.SHORT_VIDEO,
        hue=285,
        tone_hz=523,
    ),
)


class FixtureStoryPool:
    def __init__(
        self,
        stories: Sequence[Story],
        manifests: dict[UUID, ProductionManifest],
    ) -> None:
        self._stories = {story.story_id: story for story in stories}
        self._manifests = manifests

    async def get(self, story_id: UUID) -> Story:
        return self._stories[story_id]

    async def list(
        self,
        *,
        status: StoryStatus | None,
        limit: int,
        offset: int,
    ) -> Sequence[Story]:
        values = list(self._stories.values())
        if status is not None:
            values = [story for story in values if story.status is status]
        return values[offset : offset + limit]

    async def production_manifest(self, story_id: UUID) -> ProductionManifest:
        return self._manifests[story_id]


class FixtureSourceVideoLibrary:
    def __init__(self, assets: Sequence[SourceVideoRenderAsset]) -> None:
        self._assets = list(assets)

    async def approved_for_stories(
        self,
        story_ids: Sequence[UUID],
    ) -> Sequence[SourceVideoRenderAsset]:
        selected = set(story_ids)
        return [asset for asset in self._assets if asset.story_id in selected]


class RequiredDemoPolicyDirector:
    """Keep LLM ordering and bridges while enforcing the demo's acceptance policy."""

    def __init__(self, base: ProgramDirector) -> None:
        self._base = base

    @property
    def name(self) -> str:
        return f"{self._base.name}+e2e-policy"

    async def direct(
        self,
        *,
        batch_id: UUID,
        title: str,
        sources: Sequence[VideoBatchStory],
        source_video_story_ids: frozenset[UUID],
    ) -> DirectedProgramDraft:
        draft = await self._base.direct(
            batch_id=batch_id,
            title=title,
            sources=sources,
            source_video_story_ids=source_video_story_ids,
        )
        directed_stories = [
            story.model_copy(
                update={
                    "narration_module": (
                        EpisodeSceneModule.HOST_EVIDENCE
                        if index == 0
                        else story.narration_module
                    ),
                    "source_video_placement": (
                        SourceVideoPlacement.AFTER_STORY
                        if story.story_id in source_video_story_ids
                        else SourceVideoPlacement.OMIT
                    ),
                }
            )
            for index, story in enumerate(draft.direction.stories)
        ]
        direction = ProgramDirectorPlan(
            story_order=draft.direction.story_order,
            stories=directed_stories,
            bridges=draft.direction.bridges,
        )
        return DirectedProgramDraft(direction=direction, script=draft.script)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and verify one five-minute dual-profile god-news demonstration "
            "through the real program, TTS, Live2D, and Remotion boundaries."
        )
    )
    parser.add_argument(
        "--dsakiko-root",
        type=Path,
        default=os.environ.get("GOD_NEWS_E2E_DSAKIKO_ROOT"),
        help="DSakiko installation root. May also use GOD_NEWS_E2E_DSAKIKO_ROOT.",
    )
    parser.add_argument("--character", default="soyo")
    parser.add_argument("--speaker-id", default="dsakiko-soyo")
    parser.add_argument("--source-duration-seconds", type=int, default=51)
    parser.add_argument("--live2d-size", type=int, default=512)
    parser.add_argument("--live2d-fps", type=int, default=15)
    parser.add_argument("--render-timeout-seconds", type=float, default=7_200)
    parser.add_argument("--render-concurrency", type=int, default=8)
    parser.add_argument("--render-attempts", type=int, default=2)
    parser.add_argument(
        "--title",
        default="全球好消息系统演示 · 自制合法素材",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def discover_compositor_binary(workspace: Path, name: str) -> Path:
    executable = f"{name}.exe" if os.name == "nt" else name
    matches = sorted(
        path.resolve()
        for path in (workspace / "node_modules" / ".pnpm").glob(
            f"@remotion+compositor-*/node_modules/@remotion/compositor-*/{executable}"
        )
        if path.is_file()
    )
    if not matches:
        raise RuntimeError(f"Remotion compositor binary is unavailable: {executable}")
    return matches[-1]


async def run_process(
    *args: str,
    cwd: Path,
    timeout_seconds: float,
) -> tuple[bytes, bytes]:
    creationflags = 0x08000000 | 0x00000200 if os.name == "nt" else 0
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    if process.returncode != 0:
        detail = stderr[-4_000:].decode("utf-8", errors="replace")
        raise RuntimeError(f"Subprocess failed ({process.returncode}): {detail}")
    return stdout, stderr


def write_evidence_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 16_000)


async def generate_source_video(
    *,
    ffmpeg: Path,
    path: Path,
    duration_seconds: int,
    hue: int,
    tone_hz: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seed_root = path.parent / f".{path.stem}-seed"
    frames_root = seed_root / "frames"
    seed_path = seed_root / "seed.mp4"
    try:
        await asyncio.to_thread(
            generate_loop_frames,
            frames_root,
            hue,
            30,
            640,
            360,
        )
        seed_root.mkdir(parents=True, exist_ok=True)
        await run_process(
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "10",
            "-start_number",
            "0",
            "-i",
            str(frames_root / "frame-%03d.png"),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone_hz}:sample_rate=48000:duration=3",
            "-t",
            "3",
            "-af",
            "volume=0.04",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(seed_path),
            cwd=path.parent,
            timeout_seconds=300,
        )
        await run_process(
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(seed_path),
            "-t",
            str(duration_seconds),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(path),
            cwd=path.parent,
            timeout_seconds=max(300, duration_seconds * 10),
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, seed_root, True)


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write_rgb_png(path: Path, width: int, height: int, pixels: bytes) -> None:
    stride = width * 3
    scanlines = b"".join(
        b"\0" + pixels[offset : offset + stride]
        for offset in range(0, len(pixels), stride)
    )
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(
            b"IHDR",
            struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
        )
        + png_chunk(b"IDAT", zlib.compress(scanlines, level=6))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


def generate_loop_frames(
    frames_root: Path,
    hue: int,
    frame_count: int,
    width: int,
    height: int,
) -> None:
    frames_root.mkdir(parents=True, exist_ok=False)
    red, green, blue = (
        round(channel * 255)
        for channel in colorsys.hsv_to_rgb((hue % 360) / 360, 0.58, 0.52)
    )
    for frame in range(frame_count):
        moving_x = round((width + 180) * frame / frame_count) - 90
        pixels = bytearray(width * height * 3)
        cursor = 0
        for y in range(height):
            row_light = round(22 * y / max(1, height - 1))
            for x in range(width):
                grid = 14 if (x // 48 + y // 48) % 2 == 0 else 0
                glow = max(0, 60 - abs(x - moving_x))
                pixels[cursor] = min(255, red + row_light + grid + glow)
                pixels[cursor + 1] = min(
                    255,
                    green + row_light // 2 + grid + glow // 2,
                )
                pixels[cursor + 2] = min(255, blue + grid + glow // 3)
                cursor += 3
        write_rgb_png(
            frames_root / f"frame-{frame:03d}.png",
            width,
            height,
            bytes(pixels),
        )


def ensure_role_request(
    *,
    dsakiko_root: Path,
    character: str,
    speaker_id: str,
) -> RoleProfileCreate:
    character_root = dsakiko_root / "reference_audio" / character
    config_path = character_root / "reference_audio_and_text.json"
    voice_assets = load_dsakiko_voice_assets(
        config_path=config_path,
        dsakiko_root=dsakiko_root,
    )
    model_root = character_root / "GPT-SoVITS_models"
    gpt_weights = sorted(model_root.glob("*.ckpt"))
    sovits_weights = sorted(model_root.glob("*.pth"))
    if len(gpt_weights) != 1 or len(sovits_weights) != 1:
        raise RuntimeError(
            "E2E role import requires exactly one GPT .ckpt and one SoVITS .pth."
        )
    live2d_model = (
        dsakiko_root / "live2d_related" / character / "live2D_model" / "3.model.json"
    ).resolve(strict=True)
    return RoleProfileCreate(
        slug=f"dsakiko-{character}",
        display_name=f"DSakiko {character.title()}",
        kind=RoleKind.HOST,
        speaker_id=speaker_id,
        character_prompt="Warm, restrained Japanese global-good-news host.",
        default_emotion=SpeechEmotion.LIKE.value,
        default_spoken_language="ja",
        default_speed=1.0,
        default_pitch=0.0,
        gpt_weights_path=str(gpt_weights[0].resolve(strict=True)),
        sovits_weights_path=str(sovits_weights[0].resolve(strict=True)),
        tts_model_profile="v2Pro",
        reference_language=voice_assets.reference_language,
        emotion_refs=voice_assets.emotion_refs,
        tts_enabled=True,
        visual_assets=RoleVisualAssets(live2d_asset_ref=str(live2d_model)),
        enabled=True,
    )


async def ensure_role(
    container: AppContainer,
    request: RoleProfileCreate,
) -> RoleProfile:
    service = container.role_profiles
    if service is None:
        raise RuntimeError("Role profile service is unavailable.")
    existing = await service.list()
    matches = [role for role in existing if role.speaker_id == request.speaker_id]
    if not matches:
        return await service.create(request)
    if len(matches) != 1:
        raise RuntimeError("Multiple roles own the E2E speaker_id.")
    role = matches[0]
    for field_name in RoleProfileCreate.model_fields:
        if getattr(role, field_name) != getattr(request, field_name):
            raise RuntimeError(
                "The existing E2E role differs from the requested DSakiko import. "
                "Resolve it through the versioned role UI before rerunning."
            )
    return role


def build_story(
    *,
    spec: DemoStorySpec,
    speaker_id: str,
    source_audio: Path,
    index: int,
    content_instance_id: str,
) -> tuple[Story, ProductionManifest]:
    original_text = (
        f"{spec.original_text}\n\nE2E fixture instance: {content_instance_id}/{index + 1}."
    )
    source = FetchedDocument.from_text(
        TextSource(
            text=original_text,
            title=spec.title,
            language="en",
        )
    ).source
    segment = ScriptSegment(
        sequence=0,
        spoken_text=spec.spoken_text,
        spoken_language="ja",
        captions=[
            CaptionVariant(
                language="ja",
                kind=CaptionKind.VERBATIM,
                text=spec.spoken_text,
            ),
            CaptionVariant(
                language="zh-CN",
                kind=CaptionKind.TRANSLATION,
                text=spec.caption_text,
            ),
        ],
        speaker_id=speaker_id,
        emotion=(SpeechEmotion.LIKE if index % 2 == 0 else SpeechEmotion.HAPPINESS),
        scene_transition=(
            SceneTransition.CROSSFADE if index % 2 == 0 else SceneTransition.SLIDE
        ),
        speed=1.0,
        pitch=0.0,
        visual_hint=f"Evidence panel for: {spec.title}",
    )
    script = ScriptDocument(
        title=spec.title,
        spoken_language="ja",
        segments=[segment],
    )
    source_audio_sha = sha256_file(source_audio)
    source_clip = AudioClip(
        segment_id=segment.segment_id,
        path=str(source_audio),
        duration_ms=1_000,
        sample_rate_hz=16_000,
        channels=1,
        sha256=source_audio_sha,
    )
    digest = "0" * 64
    audio = AudioBundle(
        revision=script.revision,
        provider="self-authored-e2e-evidence",
        model_identity="fixture-only-not-rendered",
        synthesis=SynthesisMetadata(
            seed=0,
            reference_audio_sha256=digest,
            runtime_config_sha256=digest,
            gpt_weights_sha256=digest,
            sovits_weights_sha256=digest,
            prompt_language="ja",
            text_language="ja",
        ),
        clips=[source_clip],
    )
    story = Story(
        status=StoryStatus.DONE,
        title=spec.title,
        source=cast(SourceSnapshot, source),
        original_text=original_text,
        target_language="zh-CN",
        preferences=ScriptPreferences(
            style="warm, concise global-good-news bulletin",
            target_duration_seconds=8,
            speaker_id=speaker_id,
            emotion=segment.emotion,
            speed=1.0,
            pitch=0.0,
            spoken_language="ja",
            caption_language="zh-CN",
        ),
        translation=TranslationResult(
            source_language="en",
            target_language="zh-CN",
            translated_text=spec.caption_text,
            summary=spec.caption_text,
            key_points=[spec.caption_text],
            screening=EditorialScreening(
                model_category=spec.category,
                category=spec.category,
                model_candidate_recommendation=True,
                candidate_recommendation=True,
                confidence=1.0,
                rationale="Self-authored, non-political E2E fixture approved for this demo.",
            ),
        ),
        script=script,
        audio=audio,
        created_at=utc_now() + timedelta(seconds=index),
        updated_at=utc_now() + timedelta(seconds=index),
    )
    manifest = ProductionManifest(
        story_id=story.story_id,
        script_revision=script.revision,
        spoken_language=script.spoken_language,
        total_duration_ms=source_clip.duration_ms,
        timeline=[
            TimelineSegment(
                segment_id=segment.segment_id,
                sequence=0,
                start_ms=0,
                end_ms=source_clip.duration_ms,
                spoken_text=segment.spoken_text,
                spoken_language=segment.spoken_language,
                captions=segment.captions,
                speaker_id=segment.speaker_id,
                emotion=segment.emotion,
                scene_transition=segment.scene_transition,
                visual_hint=segment.visual_hint,
                audio_path=source_clip.path,
            )
        ],
    )
    return story, manifest


def timed_source_captions(
    spec: DemoStorySpec,
    duration_ms: int,
) -> list[TimedCaptionCue]:
    count = len(spec.source_captions)
    cues: list[TimedCaptionCue] = []
    for index, (source_text, translated_text) in enumerate(spec.source_captions):
        start = round(duration_ms * index / count)
        end = round(duration_ms * (index + 1) / count)
        cues.append(
            TimedCaptionCue(
                sequence=index,
                start_ms=start,
                end_ms=end,
                captions=[
                    CaptionVariant(
                        language="en",
                        kind=CaptionKind.VERBATIM,
                        text=source_text,
                    ),
                    CaptionVariant(
                        language="zh-CN",
                        kind=CaptionKind.TRANSLATION,
                        text=translated_text,
                    ),
                ],
            )
        )
    return cues


async def build_source_assets(
    *,
    ffmpeg: Path,
    inspector: FFprobeSourceVideoInspector,
    source_root: Path,
    stories: Sequence[Story],
    duration_seconds: int,
) -> list[SourceVideoRenderAsset]:
    semaphore = asyncio.Semaphore(2)

    async def build_one(
        index: int,
        story: Story,
        spec: DemoStorySpec,
    ) -> SourceVideoRenderAsset:
        path = source_root / f"{index + 1:02d}-{story.story_id}.mp4"
        async with semaphore:
            await generate_source_video(
                ffmpeg=ffmpeg,
                path=path,
                duration_seconds=duration_seconds,
                hue=spec.hue,
                tone_hz=spec.tone_hz,
            )
        probe = await inspector.inspect(path)
        if probe.audio_codec is None:
            raise RuntimeError("Generated source fixture is missing its original audio track.")
        return SourceVideoRenderAsset(
            asset_id=uuid4(),
            story_id=story.story_id,
            transcription_id=uuid4(),
            transcription_version=2,
            transcription_review=TranscriptReview(
                reviewer_id="e2e-fixture-editor",
                decision=TranscriptReviewDecision.APPROVE,
                reviewed_version=1,
            ),
            local_path=str(path.resolve()),
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            duration_ms=probe.duration_ms,
            width=probe.width,
            height=probe.height,
            in_ms=0,
            out_ms=probe.duration_ms,
            audio_mode=SourceVideoAudioMode.ORIGINAL,
            source_label=f"Self-generated E2E fixture · {spec.title}",
            captions=timed_source_captions(spec, probe.duration_ms),
        )

    return list(
        await asyncio.gather(
            *[
                build_one(index, story, DEMO_STORIES[index])
                for index, story in enumerate(stories)
            ]
        )
    )


async def extract_representative_frames(
    *,
    ffmpeg: Path,
    artifact: VideoRenderArtifact,
    frame_root: Path,
) -> dict[str, list[str]]:
    await asyncio.to_thread(frame_root.mkdir, parents=True, exist_ok=True)
    result: dict[str, list[str]] = {}
    for output in artifact.outputs:
        duration_seconds = output.duration_in_frames / output.fps
        times = (1.0, duration_seconds / 2, max(1.0, duration_seconds - 1.0))
        paths: list[str] = []
        for label, second in zip(("start", "middle", "end"), times, strict=True):
            path = frame_root / f"{output.profile_id.value}-{label}.png"
            await run_process(
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{second:.3f}",
                "-i",
                output.local_path,
                "-frames:v",
                "1",
                str(path),
                cwd=frame_root,
                timeout_seconds=120,
            )
            paths.append(str(path.resolve()))
        result[output.profile_id.value] = paths
    return result


def build_report(
    *,
    started_at: datetime,
    finished_at: datetime,
    role: RoleProfile,
    batch: VideoBatch,
    artifact: VideoRenderArtifact,
    source_assets: Sequence[SourceVideoRenderAsset],
    frame_paths: dict[str, list[str]],
) -> dict[str, object]:
    narration = batch.narration
    remotion_props = batch.remotion_props
    if (
        narration.direction is None
        or narration.audio is None
        or remotion_props is None
        or remotion_props.episode_plan is None
    ):
        raise RuntimeError("Rendered E2E batch is missing its reviewed program evidence.")
    return {
        "schema_version": "1.0",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "batch_id": str(batch.batch_id),
        "batch_version": batch.version,
        "program_status": batch.status.value,
        "role": {
            "profile_id": str(role.profile_id),
            "speaker_id": role.speaker_id,
            "version": role.version,
            "emotion_reference_count": len(role.emotion_refs),
            "tts_model_profile": role.tts_model_profile,
            "reference_language": role.reference_language,
            "live2d_configured": role.visual_assets.live2d_asset_ref is not None,
        },
        "director_plan": narration.direction.model_dump(mode="json"),
        "program_script": narration.script.model_dump(mode="json"),
        "program_audio": narration.audio.model_dump(mode="json"),
        "episode_plan": remotion_props.episode_plan.model_dump(mode="json"),
        "source_assets": [
            {
                **asset.model_dump(mode="json", exclude={"local_path"}),
                "local_path": asset.local_path,
                "creator": "god-news E2E fixture generator",
                "rights_status": "self_generated_publishable_demo",
                "attribution_required": False,
            }
            for asset in source_assets
        ],
        "host_assets": [
            asset.model_dump(mode="json")
            for asset in batch.visual_reservations.host_videos
        ],
        "render_artifact": artifact.model_dump(mode="json"),
        "representative_frames": frame_paths,
    }


async def main() -> None:
    args = parse_args()
    if args.dsakiko_root is None:
        raise SystemExit(
            "--dsakiko-root or GOD_NEWS_E2E_DSAKIKO_ROOT is required for real Live2D/TTS."
        )
    dsakiko_root = args.dsakiko_root.expanduser().resolve(strict=True)
    if args.source_duration_seconds < 45 or args.source_duration_seconds > 60:
        raise SystemExit("--source-duration-seconds must stay between 45 and 60.")
    if args.live2d_size % 2:
        raise SystemExit("--live2d-size must be even.")
    if args.render_attempts < 1 or args.render_attempts > 3:
        raise SystemExit("--render-attempts must stay between 1 and 3.")

    started_at = datetime.now(UTC)
    run_id = f"{started_at:%Y%m%dT%H%M%SZ}-{uuid4()}"
    settings: Settings = get_settings()
    run_root = (settings.output_dir / "e2e" / run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    source_root = run_root / "source-videos"
    render_root = run_root / "renders"
    live2d_root = run_root / "live2d"
    frame_root = run_root / "representative-frames"
    report_path = run_root / "artifact-report.json"
    source_audio = run_root / "source-story-evidence.wav"
    write_evidence_wav(source_audio)

    ffmpeg = discover_compositor_binary(WORKSPACE, "ffmpeg")
    ffprobe = discover_compositor_binary(WORKSPACE, "ffprobe")
    inspector = FFprobeSourceVideoInspector(ffprobe, timeout_seconds=60)

    container = await build_container(settings)
    try:
        if container.database is None or container.role_profiles is None:
            raise RuntimeError("Database-backed role and video services are required.")
        role_request = ensure_role_request(
            dsakiko_root=dsakiko_root,
            character=args.character,
            speaker_id=args.speaker_id,
        )
        role = await ensure_role(container, role_request)

        stories: list[Story] = []
        manifests: dict[UUID, ProductionManifest] = {}
        for index, spec in enumerate(DEMO_STORIES):
            story, manifest = build_story(
                spec=spec,
                speaker_id=role.speaker_id,
                source_audio=source_audio,
                index=index,
                content_instance_id=run_id,
            )
            stories.append(story)
            manifests[story.story_id] = manifest
        for story in stories:
            await container.repository.create(story)

        source_assets = await build_source_assets(
            ffmpeg=ffmpeg,
            inspector=inspector,
            source_root=source_root,
            stories=stories,
            duration_seconds=args.source_duration_seconds,
        )
        if not isinstance(container.generator, OpenAICompatibleTextGenerator):
            raise RuntimeError("A configured OpenAI-compatible LLM is required.")
        director = RequiredDemoPolicyDirector(
            OpenAICompatibleProgramDirector(container.generator)
        )
        host_renderer = LocalLive2DHostRenderer(
            profiles=container.role_profiles,
            python_executable=dsakiko_root / "runtime" / "python.exe",
            worker_script=WORKSPACE / "scripts" / "render_live2d_host.py",
            inspector=inspector,
            output_root=live2d_root,
            trusted_asset_roots=[dsakiko_root],
            timeout_seconds=900,
            max_parallel_segments=1,
            width=args.live2d_size,
            height=args.live2d_size,
            fps=args.live2d_fps,
        )
        renderer = LocalRemotionBatchVideoRenderer(
            package_dir=settings.video_remotion_package_dir,
            output_dir=render_root,
            node_command=settings.video_node_command,
            timeout_seconds=args.render_timeout_seconds,
            max_parallel_batches=1,
            concurrency=args.render_concurrency,
        )
        service = VideoBatchService(
            story_pool=FixtureStoryPool(stories, manifests),
            repository=SqlAlchemyVideoBatchRepository(container.database.sessions),
            host_renderer=host_renderer,
            program_director=director,
            synthesizer=container.synthesizer,
            video_renderer=renderer,
            bgm_catalog=LocalBgmCatalog(run_root / "bgm"),
            source_video_library=FixtureSourceVideoLibrary(source_assets),
            audio_root=settings.output_dir,
        )

        batch = await service.create(
            CreateVideoBatch(
                title=args.title,
                subtitle="日语本地口播 · 中文字幕 · 自制原视频素材",
                story_ids=[story.story_id for story in stories],
                max_stories=len(stories),
            )
        )
        batch = await service.submit_narration_review(
            batch.batch_id,
            SubmitNarrationReview(
                expected_batch_version=batch.version,
                decision=NarrationReviewDecision.APPROVE,
                reviewer_id="e2e-development-reviewer",
                note="Development-only automatic approval of self-authored fixture content.",
            ),
        )
        batch = await service.synthesize_narration(
            batch.batch_id,
            SynthesizeBatchNarration(expected_batch_version=batch.version),
        )
        if batch.narration_failure is not None:
            raise RuntimeError(batch.narration_failure.message)
        if batch.remotion_props is None or batch.narration.manifest is None:
            raise RuntimeError("Program synthesis completed without render semantics.")

        expected_duration_ms = (
            batch.narration.manifest.total_duration_ms
            + sum(asset.out_ms - asset.in_ms for asset in batch.remotion_props.source_videos)
            + batch.remotion_props.intro_duration_ms
            + batch.remotion_props.outro_duration_ms
            + batch.remotion_props.transition_duration_ms
            * (
                len(batch.remotion_props.episode_plan.scenes)
                if batch.remotion_props.outro_duration_ms > 0
                else len(batch.remotion_props.episode_plan.scenes) - 1
            )
        )
        if not 285_000 <= expected_duration_ms <= 315_000:
            raise RuntimeError(
                f"Compiled E2E duration {expected_duration_ms / 1000:.2f}s "
                "is outside the required five-minute acceptance window."
            )
        batch = await service.submit_timeline_review(
            batch.batch_id,
            SubmitTimelineReview(
                expected_batch_version=batch.version,
                decision=TimelineReviewDecision.APPROVE,
                reviewer_id="e2e-development-reviewer",
                note="Development-only approval after typed timeline validation.",
                story_order=[story.story_id for story in batch.stories],
            ),
        )
        for attempt in range(1, args.render_attempts + 1):
            try:
                batch = await service.render(
                    batch.batch_id,
                    expected_version=batch.version,
                )
                break
            except VideoRenderingError as exc:
                if attempt >= args.render_attempts:
                    raise
                batch = await service.get(batch.batch_id)
                if batch.status.value != "FAILED":
                    raise RuntimeError(
                        "Render retry requires the batch to persist an explicit FAILED state."
                    ) from exc
        if not isinstance(batch.artifact, VideoRenderArtifact):
            raise RuntimeError("Real dual-profile render artifact was not produced.")

        for output in batch.artifact.outputs:
            probe = await inspector.inspect(Path(output.local_path))
            expected_profile = next(
                profile
                for profile in batch.remotion_props.output_profiles
                if profile.profile_id is output.profile_id
            )
            if (
                probe.width != expected_profile.width
                or probe.height != expected_profile.height
                or probe.audio_codec is None
                or abs(probe.duration_ms - expected_duration_ms) > 1_500
            ):
                raise RuntimeError(
                    f"Rendered profile failed media verification: {output.profile_id.value}"
                )
        frames = await extract_representative_frames(
            ffmpeg=ffmpeg,
            artifact=batch.artifact,
            frame_root=frame_root,
        )
        finished_at = datetime.now(UTC)
        report = build_report(
            started_at=started_at,
            finished_at=finished_at,
            role=role,
            batch=batch,
            artifact=batch.artifact,
            source_assets=source_assets,
            frame_paths=frames,
        )
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "batch_id": str(batch.batch_id),
                    "duration_ms": expected_duration_ms,
                    "outputs": [
                        {
                            "profile_id": output.profile_id.value,
                            "path": output.local_path,
                            "size_bytes": output.size_bytes,
                            "sha256": output.sha256,
                        }
                        for output in batch.artifact.outputs
                    ],
                    "report": str(report_path),
                    "frames": frames,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await container.aclose()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
