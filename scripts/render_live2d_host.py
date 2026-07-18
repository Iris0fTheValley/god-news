from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import wave
from array import array
from collections.abc import Iterator
from contextlib import suppress
from fractions import Fraction
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))

from god_news.live2d_control import (  # noqa: E402
    CONTROLLED_PARAMETERS,
    PARAM_EYE_L_OPEN,
    PARAM_EYE_R_OPEN,
    PARAM_MOUTH_OPEN_Y,
    BlinkController,
    Live2DControlMode,
    MotionState,
    MotionTransitionController,
    MotionTransitionSettings,
    MouthController,
    MouthSettings,
    ParameterContribution,
    ParameterMixer,
    ParameterRange,
    ProceduralPoseController,
    effective_parameter_owner,
)
from god_news.live2d_diagnostics import (  # noqa: E402
    compute_signal_metrics,
    evaluate_image_tracks,
    evaluate_signal,
    robust_audio_calibration,
    threshold_for_parameter,
)


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
    parser.add_argument("--mouth-attack-ms", type=float, default=55.0)
    parser.add_argument("--mouth-release-ms", type=float, default=160.0)
    parser.add_argument(
        "--control-mode",
        choices=[mode.value for mode in Live2DControlMode],
        default=Live2DControlMode.FINAL.value,
    )
    parser.add_argument("--diagnostic-trace", type=Path)
    parser.add_argument("--seed", type=int, default=42)
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


def _read_pcm_rms(audio_path: Path, *, fps: int, frame_count: int) -> list[float]:
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
        rms = _pcm_rms(window, sample_width=sample_width)
        full_scale = float((1 << (sample_width * 8 - 1)) - 1)
        envelope.append(max(0.0, min(1.0, rms / full_scale)))
    return envelope


def _pcm_rms(window: bytes, *, sample_width: int) -> float:
    if not window:
        return 0.0
    if sample_width == 1:
        samples = (value - 128 for value in window)
        count = len(window)
    elif sample_width in {2, 4}:
        values = array("h" if sample_width == 2 else "i")
        usable = len(window) - len(window) % sample_width
        values.frombytes(window[:usable])
        if sys.byteorder != "little":
            values.byteswap()
        samples = iter(values)
        count = len(values)
    elif sample_width == 3:
        usable = len(window) - len(window) % 3

        def signed_24_bit_samples() -> Iterator[int]:
            for offset in range(0, usable, 3):
                value = int.from_bytes(
                    window[offset : offset + 3],
                    byteorder="little",
                    signed=False,
                )
                yield value - (1 << 24) if value & (1 << 23) else value

        samples = signed_24_bit_samples()
        count = usable // 3
    else:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    if count == 0:
        return 0.0
    square_sum = sum(sample * sample for sample in samples)
    return math.sqrt(square_sum / count)


def _read_pcm_envelope(audio_path: Path, *, fps: int, frame_count: int) -> list[float]:
    """Compatibility helper retained for focused envelope tests."""

    raw = _read_pcm_rms(audio_path, fps=fps, frame_count=frame_count)
    noise_floor, normalization_peak = robust_audio_calibration(raw)
    controller = MouthController(
        MouthSettings(
            noise_floor=noise_floor,
            normalization_peak=normalization_peak,
            attack_seconds=0.045,
            release_seconds=0.14,
        )
    )
    return [
        controller.update(value, delta_seconds=1 / fps).final_value
        for value in raw
    ]


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


def _expression_values(
    model_path: Path,
    model_data: dict[str, object],
    expression_name: str | None,
    parameter_ranges: dict[str, ParameterRange],
) -> dict[str, float]:
    """Compile a Cubism 2 expression into absolute baseline values.

    The SDK defaults an omitted ``calc`` field to ``add``.  Compiling the
    expression here keeps it inside the typed mixer instead of allowing a
    second SDK controller to mutate production parameters after ownership has
    been decided.
    """

    if expression_name is None:
        return {}
    expressions = model_data.get("expressions")
    if not isinstance(expressions, list):
        return {}
    entry = next(
        (
            item
            for item in expressions
            if isinstance(item, dict)
            and item.get("name") == expression_name
            and isinstance(item.get("file"), str)
        ),
        None,
    )
    if entry is None:
        return {}
    expression_path = (model_path.parent / str(entry["file"])).resolve(strict=True)
    if not expression_path.is_file():
        raise RuntimeError(f"Live2D expression is not a file: {expression_path}")
    expression_data = json.loads(expression_path.read_text(encoding="utf-8-sig"))
    params = expression_data.get("params")
    if not isinstance(params, list):
        return {}
    values: dict[str, float] = {}
    for raw in params:
        if not isinstance(raw, dict):
            continue
        parameter = raw.get("id")
        raw_value = raw.get("val")
        if parameter not in parameter_ranges or not isinstance(raw_value, (int, float)):
            continue
        parameter_range = parameter_ranges[parameter]
        base = parameter_range.default
        calculation = str(raw.get("calc", "add")).casefold()
        value = float(raw_value)
        if calculation == "add":
            compiled = base + value - float(raw.get("def", 0.0))
        elif calculation == "mult":
            default = float(raw.get("def", 1.0)) or 1.0
            compiled = base * value / default
        elif calculation == "set":
            compiled = value
        else:
            raise RuntimeError(
                f"Unsupported Live2D expression calculation {calculation!r}"
            )
        values[parameter] = parameter_range.clamp(compiled)
    return values


def _motion_file(
    model_path: Path,
    model_data: dict[str, object],
    group: str | None,
    index: int,
) -> Path | None:
    motions = model_data.get("motions")
    if group is None or not isinstance(motions, dict):
        return None
    entries = motions.get(group)
    if not isinstance(entries, list) or not 0 <= index < len(entries):
        return None
    entry = entries[index]
    if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
        return None
    path = (model_path.parent / entry["file"]).resolve(strict=True)
    return path if path.is_file() else None


def _motion_metadata(path: Path | None) -> dict[str, int | float | str | None]:
    metadata: dict[str, int | float | str | None] = {
        "file": path.name if path is not None else None,
        "fps": None,
        "fade_in_ms": None,
        "fade_out_ms": None,
        "frames": None,
    }
    if path is None:
        return metadata
    frame_count: int | None = None
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            clean = line.strip()
            if clean.startswith("$fps="):
                metadata["fps"] = int(clean.split("=", 1)[1])
            elif clean.startswith("$fadein="):
                metadata["fade_in_ms"] = float(clean.split("=", 1)[1])
            elif clean.startswith("$fadeout="):
                metadata["fade_out_ms"] = float(clean.split("=", 1)[1])
            elif frame_count is None and clean.startswith("PARAM_") and "=" in clean:
                frame_count = len(clean.split("=", 1)[1].split(","))
    metadata["frames"] = frame_count
    return metadata


def _parameter_ranges(model: object) -> dict[str, ParameterRange]:
    ranges: dict[str, ParameterRange] = {}
    for index in range(model.GetParameterCount()):
        parameter = model.GetParameter(index)
        if parameter.id in CONTROLLED_PARAMETERS:
            ranges[parameter.id] = ParameterRange(
                minimum=float(parameter.min),
                maximum=float(parameter.max),
                default=float(parameter.default),
            )
    return ranges


def _parameter_values(
    model: object,
    parameter_indexes: dict[str, int],
    parameters: set[str],
) -> dict[str, float]:
    return {
        parameter: float(model.GetParameter(parameter_indexes[parameter]).value)
        for parameter in parameters
    }


def _serialize_contribution(
    contribution: ParameterContribution,
) -> dict[str, float | str | None]:
    return {
        "base": contribution.base,
        "motion": contribution.motion,
        "expression": contribution.expression,
        "idle": contribution.idle,
        "look": contribution.look,
        "breath": contribution.breath,
        "blink": contribution.blink,
        "lip_sync": contribution.lip_sync,
        "desired": contribution.desired,
        "final": contribution.final,
        "owner": contribution.owner.value,
    }


def _legacy_contributions(
    *,
    base_values: dict[str, float],
    motion_values: dict[str, float],
    idle: dict[str, float],
    blink: float,
    mouth: float,
    parameter_ranges: dict[str, ParameterRange],
) -> dict[str, ParameterContribution]:
    contributions: dict[str, ParameterContribution] = {}
    for parameter, parameter_range in parameter_ranges.items():
        motion = motion_values.get(parameter, base_values[parameter])
        idle_value = idle.get(parameter)
        desired = motion + (idle_value or 0.0)
        blink_value: float | None = None
        lip_sync: float | None = None
        if parameter in {PARAM_EYE_L_OPEN, PARAM_EYE_R_OPEN}:
            blink_value = blink
            desired = motion * blink
        elif parameter == PARAM_MOUTH_OPEN_Y:
            lip_sync = mouth
            desired = mouth
        final = parameter_range.clamp(desired)
        contributions[parameter] = ParameterContribution(
            base=base_values[parameter],
            motion=motion,
            expression=None,
            idle=idle_value,
            look=None,
            breath=None,
            blink=blink_value,
            lip_sync=lip_sync,
            desired=desired,
            final=final,
            owner=effective_parameter_owner(
                Live2DControlMode.LEGACY_CONFLICT,
                parameter,
            ),
        )
    return contributions


def _frame_image_metrics(
    rgba: object,
    previous_rgba: object | None,
) -> dict[str, float]:
    import numpy as np

    image = np.asarray(rgba, dtype=np.uint8)
    alpha = image[:, :, 3].astype(np.float32) / 255.0
    mask = alpha > 0.03
    if not np.any(mask):
        return {
            "alpha_area_ratio": 0.0,
            "centroid_x": 0.5,
            "centroid_y": 0.5,
            "alpha_spread_x": 0.0,
            "alpha_spread_y": 0.0,
            "outline_centroid_x": 0.5,
            "outline_centroid_y": 0.5,
            "perceptual_delta": 0.0,
            "alpha_delta": 0.0,
            "face_delta": 0.0,
            "eye_delta": 0.0,
            "face_signed_delta": 0.0,
            "eye_signed_delta": 0.0,
            "local_flow_x": 0.0,
            "local_flow_y": 0.0,
            "local_flow_magnitude": 0.0,
        }
    ys, xs = np.nonzero(mask)
    height, width = alpha.shape
    weights = alpha[mask]
    centroid_x = float(np.average(xs, weights=weights) / max(1, width - 1))
    centroid_y = float(np.average(ys, weights=weights) / max(1, height - 1))
    centroid_x_px = centroid_x * max(1, width - 1)
    centroid_y_px = centroid_y * max(1, height - 1)
    alpha_spread_x = float(
        np.sqrt(np.average((xs - centroid_x_px) ** 2, weights=weights))
        / max(1, width - 1)
    )
    alpha_spread_y = float(
        np.sqrt(np.average((ys - centroid_y_px) ** 2, weights=weights))
        / max(1, height - 1)
    )
    alpha_gradient_y, alpha_gradient_x = np.gradient(alpha)
    outline = np.hypot(alpha_gradient_x, alpha_gradient_y)
    outline_total = float(np.sum(outline))
    if outline_total > 1e-8:
        grid_y, grid_x = np.indices(alpha.shape)
        outline_centroid_x = float(
            np.sum(grid_x * outline) / outline_total / max(1, width - 1)
        )
        outline_centroid_y = float(
            np.sum(grid_y * outline) / outline_total / max(1, height - 1)
        )
    else:
        outline_centroid_x = centroid_x
        outline_centroid_y = centroid_y
    metrics = {
        "alpha_area_ratio": float(np.mean(mask)),
        "centroid_x": centroid_x,
        "centroid_y": centroid_y,
        "alpha_spread_x": alpha_spread_x,
        "alpha_spread_y": alpha_spread_y,
        "outline_centroid_x": outline_centroid_x,
        "outline_centroid_y": outline_centroid_y,
        "perceptual_delta": 0.0,
        "alpha_delta": 0.0,
        "face_delta": 0.0,
        "eye_delta": 0.0,
        "face_signed_delta": 0.0,
        "eye_signed_delta": 0.0,
        "local_flow_x": 0.0,
        "local_flow_y": 0.0,
        "local_flow_magnitude": 0.0,
    }
    if previous_rgba is None:
        return metrics
    previous = np.asarray(previous_rgba, dtype=np.uint8)
    previous_alpha = previous[:, :, 3].astype(np.float32) / 255.0
    union = mask | (previous_alpha > 0.03)
    current_luma = (
        image[:, :, 0].astype(np.float32) * 0.2126
        + image[:, :, 1].astype(np.float32) * 0.7152
        + image[:, :, 2].astype(np.float32) * 0.0722
    )
    previous_luma = (
        previous[:, :, 0].astype(np.float32) * 0.2126
        + previous[:, :, 1].astype(np.float32) * 0.7152
        + previous[:, :, 2].astype(np.float32) * 0.0722
    )
    luma_delta = np.abs(current_luma - previous_luma) / 255.0
    signed_luma_delta = (current_luma - previous_luma) / 255.0
    metrics["perceptual_delta"] = float(np.mean(luma_delta[union]))
    metrics["alpha_delta"] = float(np.mean(np.abs(alpha - previous_alpha)))
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    box_width = max(1, x1 - x0)
    box_height = max(1, y1 - y0)
    face_x0 = x0 + int(box_width * 0.18)
    face_x1 = x1 - int(box_width * 0.18)
    face_y0 = y0
    face_y1 = min(y1, y0 + int(box_height * 0.42))
    eye_y0 = y0 + int(box_height * 0.13)
    eye_y1 = min(face_y1, y0 + int(box_height * 0.27))
    if face_x1 > face_x0 and face_y1 > face_y0:
        face_slice = np.s_[face_y0:face_y1, face_x0:face_x1]
        metrics["face_delta"] = float(np.mean(luma_delta[face_slice]))
        metrics["face_signed_delta"] = float(
            np.mean(signed_luma_delta[face_slice])
        )
    if face_x1 > face_x0 and eye_y1 > eye_y0:
        eye_slice = np.s_[eye_y0:eye_y1, face_x0:face_x1]
        metrics["eye_delta"] = float(np.mean(luma_delta[eye_slice]))
        metrics["eye_signed_delta"] = float(
            np.mean(signed_luma_delta[eye_slice])
        )
    # Pure-numpy, low-resolution Lucas-Kanade flow.  The 3x3 local grid
    # catches regional back-and-forth motion without adding an OpenCV runtime
    # dependency to the isolated DSakiko interpreter.
    sample_step = max(1, min(height, width) // 72)
    sampled_current = (current_luma * alpha)[::sample_step, ::sample_step] / 255.0
    sampled_previous = (
        previous_luma * previous_alpha
    )[::sample_step, ::sample_step] / 255.0
    sampled_mask = (
        (alpha > 0.03) | (previous_alpha > 0.03)
    )[::sample_step, ::sample_step]
    if min(sampled_current.shape) >= 9:
        average = (sampled_current + sampled_previous) * 0.5
        gradient_y, gradient_x = np.gradient(average)
        temporal = sampled_current - sampled_previous
        flow_vectors: list[tuple[float, float]] = []
        inner_height, inner_width = sampled_current.shape
        for row in range(3):
            y_start = row * inner_height // 3
            y_end = (row + 1) * inner_height // 3
            for column in range(3):
                x_start = column * inner_width // 3
                x_end = (column + 1) * inner_width // 3
                local_mask = sampled_mask[y_start:y_end, x_start:x_end]
                if int(np.count_nonzero(local_mask)) < 12:
                    continue
                local_x = gradient_x[y_start:y_end, x_start:x_end][local_mask]
                local_y = gradient_y[y_start:y_end, x_start:x_end][local_mask]
                local_t = temporal[y_start:y_end, x_start:x_end][local_mask]
                a_xx = float(np.dot(local_x, local_x)) + 1e-4
                a_xy = float(np.dot(local_x, local_y))
                a_yy = float(np.dot(local_y, local_y)) + 1e-4
                b_x = -float(np.dot(local_x, local_t))
                b_y = -float(np.dot(local_y, local_t))
                determinant = a_xx * a_yy - a_xy * a_xy
                if determinant <= 1e-10:
                    continue
                flow_x = (a_yy * b_x - a_xy * b_y) / determinant
                flow_y = (a_xx * b_y - a_xy * b_x) / determinant
                flow_vectors.append(
                    (flow_x / max(1, inner_width), flow_y / max(1, inner_height))
                )
        if flow_vectors:
            metrics["local_flow_x"] = float(
                np.median([value[0] for value in flow_vectors])
            )
            metrics["local_flow_y"] = float(
                np.median([value[1] for value in flow_vectors])
            )
            metrics["local_flow_magnitude"] = float(
                np.median([math.hypot(*value) for value in flow_vectors])
            )
    return metrics


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
    trace_path = (
        args.diagnostic_trace.expanduser().resolve()
        if args.diagnostic_trace is not None
        else output_path.with_suffix(".trace.jsonl")
    )
    if trace_path.suffix.lower() != ".jsonl":
        raise ValueError("diagnostic trace must use the .jsonl extension")
    if trace_path == output_path:
        raise ValueError("diagnostic trace and video output must differ")
    model_data = _validate_model(model_path)
    control_mode = Live2DControlMode(args.control_mode)
    frame_count = max(1, round(args.duration_ms * args.fps / 1_000))
    raw_envelope = _read_pcm_rms(
        audio_path,
        fps=args.fps,
        frame_count=frame_count,
    )
    noise_floor, normalization_peak = robust_audio_calibration(raw_envelope)
    mouth_controller = MouthController(
        MouthSettings(
            noise_floor=noise_floor,
            normalization_peak=normalization_peak,
            attack_seconds=args.mouth_attack_ms / 1_000,
            release_seconds=args.mouth_release_ms / 1_000,
        )
    )
    legacy_normalized = [
        max(0.0, min(1.0, (value - 0.006) / 0.168)) ** 0.72
        for value in raw_envelope
    ]
    legacy_envelope = _smooth_envelope(
        legacy_normalized,
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
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    container = None
    trace_handle = None
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
        model.SetAutoBreathEnable(control_mode is Live2DControlMode.LEGACY_CONFLICT)

        group = _motion_group(model_data, args.emotion)
        motion_count = _motion_count(model_data, group)
        motion_index = 0
        if group is not None and control_mode is Live2DControlMode.LEGACY_CONFLICT:
            model.StartMotion(group, motion_index, 3)
        expression = _expression_name(model_data, args.emotion)
        if (
            expression is not None
            and control_mode is Live2DControlMode.LEGACY_CONFLICT
        ):
            model.SetExpression(expression)
        parameter_indexes = {
            model.GetParameter(index).id: index
            for index in range(model.GetParameterCount())
        }
        parameter_ranges = _parameter_ranges(model)
        if not parameter_ranges:
            raise RuntimeError("Live2D model exposes no supported control parameters")
        base_values = {
            parameter: parameter_range.default
            for parameter, parameter_range in parameter_ranges.items()
        }
        expression_values = _expression_values(
            model_path,
            model_data,
            expression,
            parameter_ranges,
        )
        mixer = ParameterMixer(parameter_ranges)
        procedural_controller = ProceduralPoseController(seed=args.seed)
        blink_controller = BlinkController(seed=args.seed)
        first_motion_path = _motion_file(
            model_path,
            model_data,
            group,
            motion_index,
        )
        first_motion_metadata = (
            _motion_metadata(first_motion_path)
            if first_motion_path is not None
            else None
        )
        fade_in_ms = (
            first_motion_metadata.get("fade_in_ms")
            if first_motion_metadata is not None
            else None
        )
        fade_out_ms = (
            first_motion_metadata.get("fade_out_ms")
            if first_motion_metadata is not None
            else None
        )
        motion_controller = MotionTransitionController(
            MotionTransitionSettings(
                fade_in_seconds=max(
                    0.2,
                    float(fade_in_ms) / 1_000
                    if isinstance(fade_in_ms, (int, float))
                    else 0.8,
                ),
                fade_out_seconds=max(
                    0.2,
                    float(fade_out_ms) / 1_000
                    if isinstance(fade_out_ms, (int, float))
                    else 0.8,
                ),
            )
        )

        container = av.open(os.fspath(output_path), mode="w", format="webm")
        stream = container.add_stream("libvpx-vp9", rate=args.fps)
        stream.width = args.width
        stream.height = args.height
        stream.pix_fmt = "yuva420p"
        stream.options = {"lossless": "1", "auto-alt-ref": "0"}
        rendered_frames = 0
        frame_hashes: list[str] = []
        blink_events = 0
        eyes_closed = False
        motion_restarts = 0
        mouth_deltas: list[float] = []
        previous_mouth = 0.0
        last_motion_values = dict(base_values)
        previous_final_values = dict(base_values)
        motion_state_counts: dict[str, int] = {}
        motion_source_switch_deltas: list[float] = []
        motion_final_switch_deltas: list[float] = []
        parameter_tracks: dict[str, list[float]] = {
            parameter: [] for parameter in parameter_ranges
        }
        timestamps: list[float] = []
        image_tracks: dict[str, list[float]] = {
            key: []
            for key in (
                "alpha_area_ratio",
                "centroid_x",
                "centroid_y",
                "alpha_spread_x",
                "alpha_spread_y",
                "outline_centroid_x",
                "outline_centroid_y",
                "perceptual_delta",
                "alpha_delta",
                "face_delta",
                "eye_delta",
                "face_signed_delta",
                "eye_signed_delta",
                "local_flow_x",
                "local_flow_y",
                "local_flow_magnitude",
            )
        }
        previous_rgba = None
        trace_handle = trace_path.open("w", encoding="utf-8", newline="\n")
        for frame_index, raw_audio in enumerate(raw_envelope):
            timestamp_seconds = frame_index / args.fps
            delta_seconds = 1 / args.fps
            UtSystem.setUserTimeMSec(round(frame_index * 1_000 / args.fps))
            glClear(GL_COLOR_BUFFER_BIT)
            motion_switched_this_frame = False
            if control_mode is Live2DControlMode.LEGACY_CONFLICT:
                model.Update()
                motion_values = _parameter_values(
                    model,
                    parameter_indexes,
                    set(parameter_ranges),
                )
                if group is not None and motion_count > 0 and model.IsMotionFinished():
                    motion_index = (motion_index + 1) % motion_count
                    model.StartMotion(group, motion_index, 3)
                    motion_restarts += 1
                legacy_idle = {
                    parameter: value
                    for parameter, value in _idle_pose(
                        frame_index,
                        fps=args.fps,
                        intensity=args.motion_intensity,
                    ).items()
                    if parameter in parameter_ranges
                }
                blink = _blink_openness(frame_index, fps=args.fps)
                mouth_frame = mouth_controller.update(
                    raw_audio,
                    delta_seconds=delta_seconds,
                )
                mouth_open = legacy_envelope[frame_index]
                contributions = _legacy_contributions(
                    base_values=base_values,
                    motion_values=motion_values,
                    idle=legacy_idle,
                    blink=blink,
                    mouth=mouth_open,
                    parameter_ranges=parameter_ranges,
                )
                motion_state = "legacy_immediate_restart"
                motion_weight = 1.0
                blink_state = "legacy_periodic"
                gated_envelope = mouth_frame.gated_envelope
                smoothed_mouth_target = legacy_envelope[frame_index]
            else:
                motion_available = (
                    group is not None
                    and motion_count > 0
                    and control_mode is not Live2DControlMode.PROCEDURAL_ONLY
                )
                transition = motion_controller.update(
                    delta_seconds=delta_seconds,
                    motion_finished=(
                        bool(model.IsMotionFinished()) if motion_available else True
                    ),
                    motion_available=motion_available,
                )
                if transition.start_motion and group is not None:
                    model.StartMotion(group, motion_index, 3)
                    if rendered_frames > 0:
                        motion_restarts += 1
                        motion_switched_this_frame = True
                model.Update()
                sampled_values = _parameter_values(
                    model,
                    parameter_indexes,
                    set(parameter_ranges),
                )
                if transition.state in {MotionState.ENTERING, MotionState.PLAYING}:
                    if transition.start_motion and rendered_frames > 0:
                        motion_source_switch_deltas.append(
                            max(
                                abs(
                                    sampled_values[parameter]
                                    - last_motion_values.get(
                                        parameter,
                                        base_values[parameter],
                                    )
                                )
                                for parameter in sampled_values
                            )
                        )
                    last_motion_values = sampled_values
                if transition.completed_transition and motion_count > 0:
                    motion_index = (motion_index + 1) % motion_count
                motion_values = (
                    sampled_values
                    if transition.state in {MotionState.ENTERING, MotionState.PLAYING}
                    else last_motion_values
                )
                pose = procedural_controller.update(
                    timestamp_seconds=timestamp_seconds,
                    delta_seconds=delta_seconds,
                    motion_weight=transition.blend_weight,
                )
                blink_enabled = control_mode in {
                    Live2DControlMode.PROCEDURAL_ONLY,
                    Live2DControlMode.NO_LIP_SYNC,
                    Live2DControlMode.FINAL,
                }
                blink = blink_controller.update(
                    delta_seconds,
                    enabled=blink_enabled,
                )
                mouth_frame = mouth_controller.update(
                    raw_audio,
                    delta_seconds=delta_seconds,
                )
                mouth_open = mouth_frame.final_value
                contributions = mixer.mix(
                    delta_seconds=delta_seconds,
                    mode=control_mode,
                    base_values=base_values,
                    motion_values=motion_values,
                    motion_weight=transition.blend_weight,
                    procedural_pose=pose,
                    blink_openness=blink,
                    blink_owned=blink_enabled,
                    mouth_value=mouth_open,
                    expression_values=expression_values,
                )
                motion_state = transition.state.value
                motion_weight = transition.blend_weight
                blink_state = blink_controller.state.value
                gated_envelope = mouth_frame.gated_envelope
                smoothed_mouth_target = mouth_frame.smoothed_target
            for parameter, contribution in contributions.items():
                model.SetParameterValue(parameter, contribution.final, 1.0)
                parameter_tracks[parameter].append(contribution.final)
            if motion_switched_this_frame:
                motion_final_switch_deltas.append(
                    max(
                        abs(
                            contribution.final
                            - previous_final_values.get(parameter, contribution.base)
                        )
                        for parameter, contribution in contributions.items()
                    )
                )
            previous_final_values = {
                parameter: contribution.final
                for parameter, contribution in contributions.items()
            }
            applied_mouth = contributions[PARAM_MOUTH_OPEN_Y].final
            current_eyes_closed = (
                contributions.get(PARAM_EYE_L_OPEN) is not None
                and contributions.get(PARAM_EYE_R_OPEN) is not None
                and contributions[PARAM_EYE_L_OPEN].final < 0.18
                and contributions[PARAM_EYE_R_OPEN].final < 0.18
            )
            if current_eyes_closed and not eyes_closed:
                blink_events += 1
            eyes_closed = current_eyes_closed
            motion_state_counts[motion_state] = motion_state_counts.get(motion_state, 0) + 1
            mouth_deltas.append(abs(applied_mouth - previous_mouth))
            previous_mouth = applied_mouth
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
            display_rgba = rgba[::-1].copy()
            image_metrics = _frame_image_metrics(display_rgba, previous_rgba)
            previous_rgba = display_rgba
            for key, value in image_metrics.items():
                image_tracks[key].append(value)
            timestamps.append(timestamp_seconds)
            trace_handle.write(
                json.dumps(
                    {
                        "frame": frame_index,
                        "timestamp_ms": round(timestamp_seconds * 1_000, 6),
                        "delta_ms": round(delta_seconds * 1_000, 6),
                        "control_mode": control_mode.value,
                        "motion_group": group,
                        "motion_index": motion_index if group is not None else None,
                        "motion_state": motion_state,
                        "motion_blend_weight": motion_weight,
                        "expression": expression,
                        "blink_state": blink_state,
                        "blink_openness": blink,
                        "raw_audio_envelope": raw_audio,
                        "gated_audio_envelope": gated_envelope,
                        "smoothed_mouth_target": smoothed_mouth_target,
                        "final_mouth_value": applied_mouth,
                        "parameters": {
                            parameter: _serialize_contribution(contribution)
                            for parameter, contribution in contributions.items()
                        },
                        "image": image_metrics,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            video_frame = av.VideoFrame.from_ndarray(display_rgba, format="rgba")
            video_frame.pts = frame_index
            video_frame.time_base = Fraction(1, args.fps)
            for packet in stream.encode(video_frame):
                container.mux(packet)
            rendered_frames += 1

        trace_handle.close()
        trace_handle = None
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
        parameter_metrics: dict[str, dict[str, object]] = {}
        gate_findings: list[dict[str, object]] = []
        for parameter, track in parameter_tracks.items():
            parameter_range = parameter_ranges[parameter]
            metrics = compute_signal_metrics(
                track,
                timestamps,
                reversal_epsilon=max(1e-5, parameter_range.span * 0.0005),
            )
            threshold = threshold_for_parameter(
                parameter,
                parameter_range,
                fps=args.fps,
            )
            findings = evaluate_signal(parameter, metrics, threshold)
            parameter_metrics[parameter] = {
                "range": {
                    "minimum": parameter_range.minimum,
                    "maximum": parameter_range.maximum,
                    "default": parameter_range.default,
                },
                "metrics": metrics.as_dict(),
                "threshold": threshold.as_dict(),
                "findings": [finding.as_dict() for finding in findings],
            }
            gate_findings.extend(finding.as_dict() for finding in findings)
        image_metric_objects, image_limits, image_findings = evaluate_image_tracks(
            image_tracks,
            timestamps,
            fps=args.fps,
            frame_width=args.width,
            frame_height=args.height,
        )
        image_metrics_summary = {
            name: metrics.as_dict()
            for name, metrics in image_metric_objects.items()
        }
        gate_findings.extend(finding.as_dict() for finding in image_findings)
        trace_size = trace_path.stat().st_size
        trace_sha256 = hashlib.sha256(trace_path.read_bytes()).hexdigest()
        print(
            json.dumps(
                {
                    "schema_version": "2.0",
                    "control_mode": control_mode.value,
                    "frames": frame_count,
                    "envelope_frames": len(raw_envelope),
                    "rendered_frames": rendered_frames,
                    "fps": args.fps,
                    "time_delta_ms_min": math.floor(1_000 / args.fps),
                    "time_delta_ms_max": math.ceil(1_000 / args.fps),
                    "motion_group": group,
                    "motion_restarts": motion_restarts,
                    "motion_state_counts": motion_state_counts,
                    "motion_switch_max_delta": max(
                        motion_final_switch_deltas,
                        default=0.0,
                    ),
                    "motion_source_switch_max_delta": max(
                        motion_source_switch_deltas,
                        default=0.0,
                    ),
                    "motion_metadata": first_motion_metadata,
                    "expression": expression,
                    "blink_events": blink_events,
                    "mouth_min": min(parameter_tracks.get(PARAM_MOUTH_OPEN_Y, [0.0])),
                    "mouth_p50": _percentile(
                        parameter_tracks.get(PARAM_MOUTH_OPEN_Y, [0.0]),
                        0.5,
                    ),
                    "mouth_p95": _percentile(
                        parameter_tracks.get(PARAM_MOUTH_OPEN_Y, [0.0]),
                        0.95,
                    ),
                    "mouth_max": max(parameter_tracks.get(PARAM_MOUTH_OPEN_Y, [0.0])),
                    "mouth_max_delta": max(mouth_deltas, default=0.0),
                    "voiced_frame_ratio": (
                        sum(value > noise_floor for value in raw_envelope)
                        / len(raw_envelope)
                        if raw_envelope
                        else 0.0
                    ),
                    "exact_duplicate_pair_ratio": (
                        duplicate_pairs / max(1, len(frame_hashes) - 1)
                    ),
                    "longest_exact_duplicate_run": longest_duplicate_run,
                    "controlled_parameters": sorted(parameter_ranges),
                    "parameter_owners": {
                        parameter: contribution.owner.value
                        for parameter, contribution in contributions.items()
                    },
                    "parameter_metrics": parameter_metrics,
                    "image_metrics": image_metrics_summary,
                    "image_thresholds": image_limits,
                    "gate_findings": gate_findings,
                    "quality_gate_passed": not gate_findings,
                    "audio_calibration": {
                        "noise_floor": noise_floor,
                        "normalization_peak": normalization_peak,
                    },
                    "trace_path": str(trace_path),
                    "trace_sha256": trace_sha256,
                    "trace_size_bytes": trace_size,
                },
                separators=(",", ":"),
            )
        )
    finally:
        if container is not None:
            with suppress(Exception):
                container.close()
        if trace_handle is not None:
            with suppress(Exception):
                trace_handle.close()
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
