from __future__ import annotations

import argparse
import audioop
import hashlib
import json
import math
import os
import statistics
import sys
import wave
from collections.abc import Iterator
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
    parser.add_argument("--motion-intensity", type=float, default=0.35)
    parser.add_argument("--mouth-attack-ms", type=float, default=45.0)
    parser.add_argument("--mouth-release-ms", type=float, default=140.0)
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
        if sample_width == 1:
            # WAV stores 8-bit PCM unsigned while audioop interprets it as signed.
            pcm = audioop.bias(pcm, 1, -128)

    bytes_per_sample_frame = sample_width * channels
    envelope: list[float] = []
    for frame_index in range(frame_count):
        sample_start = round(frame_index * sample_rate / fps)
        sample_end = round((frame_index + 1) * sample_rate / fps)
        start = sample_start * bytes_per_sample_frame
        end = sample_end * bytes_per_sample_frame
        window = pcm[start:end]
        rms = audioop.rms(window, sample_width) if window else 0
        full_scale = float((1 << (sample_width * 8 - 1)) - 1)
        amplitude = rms / full_scale
        # Normalize every PCM width before applying the renderer-owned gate.
        normalized = max(0.0, min(1.0, (amplitude - 0.006) / 0.168))
        envelope.append(normalized**0.72)
    return envelope


def _smooth_envelope(
    values: list[float],
    *,
    fps: int,
    attack_ms: float,
    release_ms: float,
) -> list[float]:
    if fps < 1 or attack_ms <= 0 or release_ms <= 0:
        raise ValueError("mouth smoothing requires positive fps and time constants")
    attack = 1.0 - math.exp(-1.0 / (fps * attack_ms / 1_000.0))
    release = 1.0 - math.exp(-1.0 / (fps * release_ms / 1_000.0))
    current = 0.0
    smoothed: list[float] = []
    for target in values:
        coefficient = attack if target > current else release
        current += (target - current) * coefficient
        smoothed.append(max(0.0, min(1.0, current)))
    return smoothed


def _blink_openness(frame_index: int, *, fps: int) -> float:
    """Deterministic blink state that remains active while a motion is playing."""

    seconds = frame_index / fps
    cycle = 3.4 + 0.35 * math.sin(math.floor(seconds / 3.4) * 1.618)
    phase = seconds % cycle
    if phase >= 0.19:
        return 1.0
    if phase < 0.065:
        return max(0.0, 1.0 - phase / 0.065)
    if phase < 0.105:
        return 0.0
    return min(1.0, (phase - 0.105) / 0.085)


def _idle_pose(frame_index: int, *, fps: int, intensity: float) -> dict[str, float]:
    seconds = frame_index / fps
    return {
        "PARAM_ANGLE_X": intensity * (3.4 * math.sin(seconds * 0.61)),
        "PARAM_ANGLE_Y": intensity * (2.1 * math.sin(seconds * 0.43 + 0.8)),
        "PARAM_ANGLE_Z": intensity * (1.2 * math.sin(seconds * 0.37 + 1.7)),
        "PARAM_BODY_ANGLE_X": intensity * (1.4 * math.sin(seconds * 0.29 + 0.2)),
        "PARAM_EYE_BALL_X": intensity * (0.28 * math.sin(seconds * 0.53 + 1.2)),
        "PARAM_EYE_BALL_Y": intensity * (0.16 * math.sin(seconds * 0.41 + 2.0)),
    }


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


def _motion_count(model_data: dict[str, object], group: str | None) -> int:
    motions = model_data.get("motions")
    if group is None or not isinstance(motions, dict):
        return 0
    entries = motions.get(group)
    return len(entries) if isinstance(entries, list) else 0


def _expression_name(model_data: dict[str, object], emotion: str) -> str | None:
    expressions = model_data.get("expressions")
    if not isinstance(expressions, list):
        return None
    names = [
        item.get("name")
        for item in expressions
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]
    for candidate in (emotion, emotion.casefold(), "smile"):
        if candidate in names:
            return candidate
    return None


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return float(ordered[index])


def _successive(values: list[str]) -> Iterator[tuple[str, str]]:
    iterator = iter(values)
    try:
        previous = next(iterator)
    except StopIteration:
        return
    for current in iterator:
        yield previous, current
        previous = current


def render(args: argparse.Namespace) -> None:
    if args.duration_ms < 1:
        raise ValueError("duration-ms must be positive")
    if args.width < 2 or args.height < 2 or args.width % 2 or args.height % 2:
        raise ValueError("width and height must be positive even integers")
    if not 1 <= args.fps <= 120:
        raise ValueError("fps must be between 1 and 120")
    if not 0.05 <= args.scale <= 10:
        raise ValueError("scale must be between 0.05 and 10")
    if not 0 <= args.motion_intensity <= 1:
        raise ValueError("motion-intensity must be between 0 and 1")
    if args.mouth_attack_ms <= 0 or args.mouth_release_ms <= 0:
        raise ValueError("mouth smoothing values must be positive")

    model_path = _require_file(args.model, "model")
    audio_path = _require_file(args.audio, "audio")
    output_path = args.output.expanduser().resolve()
    if output_path.suffix.lower() != ".webm":
        raise ValueError("output must use the .webm extension")
    model_data = _validate_model(model_path)
    frame_count = max(1, round(args.duration_ms * args.fps / 1_000))
    raw_envelope = _read_pcm_envelope(
        audio_path,
        fps=args.fps,
        frame_count=frame_count,
    )
    envelope = _smooth_envelope(
        raw_envelope,
        fps=args.fps,
        attack_ms=args.mouth_attack_ms,
        release_ms=args.mouth_release_ms,
    )

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
        model.SetAutoBlinkEnable(False)
        model.SetAutoBreathEnable(True)

        group = _motion_group(model_data, args.emotion)
        motion_count = _motion_count(model_data, group)
        motion_index = 0
        if group is not None:
            model.StartMotion(group, motion_index, 3)
        expression = _expression_name(model_data, args.emotion)
        if expression is not None:
            model.SetExpression(expression)
        parameter_indexes = {
            model.GetParameter(index).id: index
            for index in range(model.GetParameterCount())
        }
        parameter_ids = set(parameter_indexes)

        container = av.open(os.fspath(output_path), mode="w", format="webm")
        stream = container.add_stream("libvpx-vp9", rate=args.fps)
        stream.width = args.width
        stream.height = args.height
        stream.pix_fmt = "yuva420p"
        stream.options = {"lossless": "1", "auto-alt-ref": "0"}
        rendered_frames = 0
        frame_hashes: list[str] = []
        blink_events = 0
        blink_active = False
        motion_restarts = 0
        mouth_deltas: list[float] = []
        previous_mouth = 0.0
        for frame_index, mouth_open in enumerate(envelope):
            UtSystem.setUserTimeMSec(round(frame_index * 1_000 / args.fps))
            glClear(GL_COLOR_BUFFER_BIT)
            model.Update()
            if group is not None and motion_count > 0 and model.IsMotionFinished():
                motion_index = (motion_index + 1) % motion_count
                model.StartMotion(group, motion_index, 3)
                motion_restarts += 1
            for parameter_id, value in _idle_pose(
                frame_index,
                fps=args.fps,
                intensity=args.motion_intensity,
            ).items():
                if parameter_id in parameter_ids:
                    model.AddParameterValue(parameter_id, value, 1.0)
            blink = _blink_openness(frame_index, fps=args.fps)
            now_blinking = blink < 0.999
            if now_blinking and not blink_active:
                blink_events += 1
            blink_active = now_blinking
            for eye_id in ("PARAM_EYE_L_OPEN", "PARAM_EYE_R_OPEN"):
                if eye_id in parameter_ids:
                    current = model.GetParameter(parameter_indexes[eye_id]).value
                    model.SetParameterValue(eye_id, current * blink, 1.0)
            if "PARAM_MOUTH_OPEN_Y" in parameter_ids:
                model.SetParameterValue("PARAM_MOUTH_OPEN_Y", mouth_open, 1.0)
            mouth_deltas.append(abs(mouth_open - previous_mouth))
            previous_mouth = mouth_open
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
            frame_hashes.append(hashlib.sha256(pixels).hexdigest())
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
        duplicate_pairs = sum(
            previous == current
            for previous, current in _successive(frame_hashes)
        )
        longest_duplicate_run = 0
        current_duplicate_run = 0
        for previous, current in _successive(frame_hashes):
            if previous == current:
                current_duplicate_run += 1
                longest_duplicate_run = max(
                    longest_duplicate_run,
                    current_duplicate_run,
                )
            else:
                current_duplicate_run = 0
        print(
            json.dumps(
                {
                    "frames": frame_count,
                    "envelope_frames": len(envelope),
                    "rendered_frames": rendered_frames,
                    "fps": args.fps,
                    "time_delta_ms_min": math.floor(1_000 / args.fps),
                    "time_delta_ms_max": math.ceil(1_000 / args.fps),
                    "motion_group": group,
                    "motion_restarts": motion_restarts,
                    "expression": expression,
                    "blink_events": blink_events,
                    "mouth_min": min(envelope, default=0.0),
                    "mouth_p50": statistics.median(envelope) if envelope else 0.0,
                    "mouth_p95": _percentile(envelope, 0.95),
                    "mouth_max": max(envelope, default=0.0),
                    "mouth_max_delta": max(mouth_deltas, default=0.0),
                    "voiced_frame_ratio": (
                        sum(value > 0.02 for value in envelope) / len(envelope)
                        if envelope
                        else 0.0
                    ),
                    "exact_duplicate_pair_ratio": (
                        duplicate_pairs / max(1, len(frame_hashes) - 1)
                    ),
                    "longest_exact_duplicate_run": longest_duplicate_run,
                    "controlled_parameters": sorted(
                        parameter_ids
                        & {
                            "PARAM_ANGLE_X",
                            "PARAM_ANGLE_Y",
                            "PARAM_ANGLE_Z",
                            "PARAM_BODY_ANGLE_X",
                            "PARAM_EYE_BALL_X",
                            "PARAM_EYE_BALL_Y",
                            "PARAM_EYE_L_OPEN",
                            "PARAM_EYE_R_OPEN",
                            "PARAM_MOUTH_OPEN_Y",
                        }
                    ),
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
