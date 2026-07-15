from __future__ import annotations

import argparse
import audioop
import json
import os
import sys
import wave
from contextlib import suppress
from fractions import Fraction
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render one deterministic Cubism 2 host clip with an alpha channel."
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emotion", default="neutral")
    parser.add_argument("--duration-ms", type=int, required=True)
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--offset-x", type=float, default=0.0)
    parser.add_argument("--offset-y", type=float, default=0.0)
    return parser


def _require_file(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a file: {resolved}")
    return resolved


def _validate_model(model_path: Path) -> dict[str, object]:
    with model_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
        raise ValueError("only Cubism 2 .model.json files are supported")
    return payload


def _read_pcm_envelope(audio_path: Path, *, fps: int, frame_count: int) -> list[float]:
    with wave.open(os.fspath(audio_path), "rb") as source:
        sample_width = source.getsampwidth()
        channels = source.getnchannels()
        sample_rate = source.getframerate()
        if sample_width not in (1, 2, 3, 4):
            raise ValueError(f"unsupported PCM sample width: {sample_width}")
        if channels < 1 or sample_rate < 1:
            raise ValueError("audio must contain PCM samples")
        pcm = source.readframes(source.getnframes())

    bytes_per_sample_frame = sample_width * channels
    envelope: list[float] = []
    for frame_index in range(frame_count):
        sample_start = round(frame_index * sample_rate / fps)
        sample_end = round((frame_index + 1) * sample_rate / fps)
        start = sample_start * bytes_per_sample_frame
        end = sample_end * bytes_per_sample_frame
        window = pcm[start:end]
        rms = audioop.rms(window, sample_width) if window else 0
        # A soft noise gate avoids a permanently moving mouth while preserving
        # normal speech dynamics. The value is deliberately renderer-owned and
        # does not leak into the editorial or role contracts.
        normalized = max(0.0, min(1.0, (rms - 180.0) / 5_500.0))
        envelope.append(normalized**0.72)
    return envelope


def _motion_group(model_data: dict[str, object], emotion: str) -> str | None:
    motions = model_data.get("motions")
    if not isinstance(motions, dict):
        return None
    candidates = (emotion, "talking_motion", "idle_motion", "IDLE")
    for candidate in candidates:
        entries = motions.get(candidate)
        if isinstance(entries, list) and entries:
            return candidate
    return None


def render(args: argparse.Namespace) -> None:
    if args.duration_ms < 1:
        raise ValueError("duration-ms must be positive")
    if args.width < 2 or args.height < 2 or args.width % 2 or args.height % 2:
        raise ValueError("width and height must be positive even integers")
    if not 1 <= args.fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    if not 0.05 <= args.scale <= 10:
        raise ValueError("scale must be between 0.05 and 10")

    model_path = _require_file(args.model, "model")
    audio_path = _require_file(args.audio, "audio")
    output_path = args.output.expanduser().resolve()
    if output_path.suffix.lower() != ".webm":
        raise ValueError("output must use the .webm extension")
    model_data = _validate_model(model_path)
    frame_count = max(1, round(args.duration_ms * args.fps / 1_000))
    envelope = _read_pcm_envelope(audio_path, fps=args.fps, frame_count=frame_count)

    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import av
    import live2d.v2cpp as live2d
    import numpy as np
    import pygame
    from live2d.v2.core import UtSystem
    from OpenGL.GL import (
        GL_BLEND,
        GL_COLOR_BUFFER_BIT,
        GL_ONE_MINUS_SRC_ALPHA,
        GL_RGBA,
        GL_SRC_ALPHA,
        GL_UNSIGNED_BYTE,
        glBlendFunc,
        glClear,
        glClearColor,
        glEnable,
        glFinish,
        glReadPixels,
        glViewport,
    )
    from pygame.locals import (
        DOUBLEBUF,
        GL_ALPHA_SIZE,
        GL_BLUE_SIZE,
        GL_GREEN_SIZE,
        GL_RED_SIZE,
        HIDDEN,
        OPENGL,
    )

    pygame.display.init()
    pygame.display.gl_set_attribute(GL_RED_SIZE, 8)
    pygame.display.gl_set_attribute(GL_GREEN_SIZE, 8)
    pygame.display.gl_set_attribute(GL_BLUE_SIZE, 8)
    pygame.display.gl_set_attribute(GL_ALPHA_SIZE, 8)
    pygame.display.set_mode((args.width, args.height), DOUBLEBUF | OPENGL | HIDDEN)
    glViewport(0, 0, args.width, args.height)
    glClearColor(0.0, 0.0, 0.0, 0.0)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    model = None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    container = None
    try:
        UtSystem.setUserTimeMSec(0)
        live2d.enableLog(False)
        live2d.init()
        live2d.glInit()
        model = live2d.LAppModel()
        model.LoadModelJson(os.fspath(model_path))
        model.Resize(args.width, args.height)
        model.SetScale(args.scale)
        model.SetOffset(args.offset_x, args.offset_y)
        model.SetAutoBlinkEnable(True)
        model.SetAutoBreathEnable(True)

        group = _motion_group(model_data, args.emotion)
        if group is not None:
            model.StartMotion(group, 0, 3)

        container = av.open(os.fspath(output_path), mode="w", format="webm")
        stream = container.add_stream("libvpx-vp9", rate=args.fps)
        stream.width = args.width
        stream.height = args.height
        stream.pix_fmt = "yuva420p"
        stream.options = {"lossless": "1", "auto-alt-ref": "0"}
        rendered_frames = 0
        for frame_index, mouth_open in enumerate(envelope):
            UtSystem.setUserTimeMSec(round(frame_index * 1_000 / args.fps))
            glClear(GL_COLOR_BUFFER_BIT)
            model.Update()
            model.SetParameterValue("PARAM_MOUTH_OPEN_Y", mouth_open)
            model.Draw()
            glFinish()
            pixels = bytes(
                glReadPixels(
                    0,
                    0,
                    args.width,
                    args.height,
                    GL_RGBA,
                    GL_UNSIGNED_BYTE,
                )
            )
            expected_bytes = args.width * args.height * 4
            if len(pixels) != expected_bytes:
                raise RuntimeError(
                    f"OpenGL returned {len(pixels)} bytes; expected {expected_bytes}"
                )
            if frame_index == 0:
                alpha = pixels[3::4]
                if not alpha or min(alpha) == max(alpha):
                    raise RuntimeError("OpenGL capture did not preserve a varying alpha channel")
            rgba = np.frombuffer(pixels, dtype=np.uint8).reshape(
                args.height,
                args.width,
                4,
            )
            video_frame = av.VideoFrame.from_ndarray(rgba[::-1].copy(), format="rgba")
            video_frame.pts = frame_index
            video_frame.time_base = Fraction(1, args.fps)
            for packet in stream.encode(video_frame):
                container.mux(packet)
            rendered_frames += 1

        for packet in stream.encode():
            container.mux(packet)
        container.close()
        container = None
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError("Live2D encoder did not create a non-empty output")
        print(
            json.dumps(
                {
                    "frames": frame_count,
                    "envelope_frames": len(envelope),
                    "rendered_frames": rendered_frames,
                    "fps": args.fps,
                },
                separators=(",", ":"),
            )
        )
    finally:
        if container is not None:
            with suppress(Exception):
                container.close()
        if model is not None:
            with suppress(Exception):
                model.StopAllMotions()
        with suppress(Exception):
            live2d.dispose()
        with suppress(Exception):
            live2d.glRelease()
        UtSystem.setUserTimeMSec(UtSystem.USER_TIME_AUTO)
        pygame.quit()


def main() -> int:
    try:
        render(_parser().parse_args())
    except Exception as exc:
        print(f"live2d-render-error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
