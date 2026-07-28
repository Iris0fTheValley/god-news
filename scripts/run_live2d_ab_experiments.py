from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
MODES = ("motion_only", "procedural_only", "no_lip_sync", "final")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render and inspect the four required Live2D isolation experiments."
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--live2d-python", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--duration-ms", type=int, required=True)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--emotion", default="happiness")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--include-legacy", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float = 1_200,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=0x08000000 | 0x00000200,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stderr[-4_000:]}"
        )
    return result


def _audio_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as source:
        return round(source.getnframes() * 1_000 / source.getframerate())


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[math.floor((len(ordered) - 1) * percentile)]


def _pcm_rms(block: bytes, *, sample_width: int) -> float:
    if not block:
        return 0.0
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    total = 0.0
    count = len(block) // sample_width
    for offset in range(0, count * sample_width, sample_width):
        sample_bytes = block[offset : offset + sample_width]
        if sample_width == 1:
            sample = sample_bytes[0] - 128
            peak = 128
        else:
            sample = int.from_bytes(sample_bytes, "little", signed=True)
            peak = 1 << (sample_width * 8 - 1)
        total += (sample / peak) ** 2
    return math.sqrt(total / max(1, count))


def _silence_bytes(frame_count: int, *, channels: int, sample_width: int) -> bytes:
    value = b"\x80" if sample_width == 1 else b"\x00" * sample_width
    return value * channels * frame_count


def _cyclic_pcm_slice(
    pcm: bytes,
    *,
    frame_size: int,
    start_frame: int,
    frame_count: int,
) -> bytes:
    source_frames = len(pcm) // frame_size
    if source_frames < 1:
        raise ValueError("source WAV contains no PCM frames")
    output = bytearray()
    cursor = start_frame % source_frames
    remaining = frame_count
    while remaining:
        available = min(remaining, source_frames - cursor)
        start = cursor * frame_size
        output.extend(pcm[start : start + available * frame_size])
        remaining -= available
        cursor = 0
    return bytes(output)


def _wave_envelope(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    frame_ms: int = 20,
) -> tuple[list[float], int]:
    frame_size = channels * sample_width
    window_frames = max(1, round(sample_rate * frame_ms / 1_000))
    window_bytes = window_frames * frame_size
    envelope = [
        _pcm_rms(pcm[offset : offset + window_bytes], sample_width=sample_width)
        for offset in range(0, len(pcm) - window_bytes + 1, window_bytes)
    ]
    return envelope, window_frames


def _pcm_neutral(block: bytes, *, sample_width: int) -> bool:
    neutral = b"\x80" if sample_width == 1 else b"\x00" * sample_width
    return bool(block) and all(
        block[offset : offset + sample_width] == neutral
        for offset in range(0, len(block) - sample_width + 1, sample_width)
    )


def _scan_diagnostic_signal(path: Path, *, window_ms: int = 20) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=True)
    with wave.open(str(resolved), "rb") as reader:
        if reader.getcomptype() != "NONE":
            raise ValueError("diagnostic input must be uncompressed PCM WAV")
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        pcm = reader.readframes(reader.getnframes())
    frame_size = channels * sample_width
    window_frames = max(1, round(sample_rate * window_ms / 1_000))
    window_bytes = window_frames * frame_size
    blocks = [
        pcm[offset : offset + window_bytes]
        for offset in range(0, len(pcm) - window_bytes + 1, window_bytes)
    ]
    envelope = [_pcm_rms(block, sample_width=sample_width) for block in blocks]
    neutral = [_pcm_neutral(block, sample_width=sample_width) for block in blocks]
    if len(envelope) < math.ceil(12_000 / window_ms):
        raise ValueError("diagnostic WAV contains fewer than twelve seconds")
    two_seconds = math.ceil(2_000 / window_ms)
    silence_candidates: list[tuple[float, float, int]] = []
    for start in range(0, len(envelope) - two_seconds + 1):
        values = envelope[start : start + two_seconds]
        exact_ratio = sum(neutral[start : start + two_seconds]) / two_seconds
        silence_candidates.append((exact_ratio, -max(values), -start))
    exact_ratio, negative_max_rms, negative_silence_start = max(silence_candidates)
    silence_start = -negative_silence_start
    if exact_ratio < 0.99 or -negative_max_rms > 0.000_01:
        raise ValueError("diagnostic WAV has no verified two-second PCM silence")
    nonzero = [value for value in envelope if value > 0.000_01]
    if not nonzero:
        raise ValueError("diagnostic WAV contains no audible signal")
    speech_threshold = max(0.003, _percentile(nonzero, 0.2) * 0.55)
    speech_candidates: list[tuple[float, int, float, float]] = []
    for start in range(0, len(envelope) - two_seconds + 1):
        values = envelope[start : start + two_seconds]
        voiced_ratio = sum(value >= speech_threshold for value in values) / len(values)
        mean = sum(values) / len(values)
        speech_candidates.append((voiced_ratio * 2 + mean, -start, voiced_ratio, mean))
    _, negative_speech_start, voiced_ratio, speech_mean = max(speech_candidates)
    speech_start = -negative_speech_start
    if voiced_ratio < 0.7 or speech_mean < 0.005:
        raise ValueError("diagnostic WAV has no verified two-second speech window")
    runs: list[tuple[int, int]] = []
    run_start: int | None = None
    for index, is_neutral in enumerate([*neutral, False]):
        if is_neutral and run_start is None:
            run_start = index
        elif not is_neutral and run_start is not None:
            runs.append((run_start, index))
            run_start = None
    short_pause_runs = [
        (start, end)
        for start, end in runs
        if start > 0
        and end < len(neutral)
        and 100 <= (end - start) * window_ms <= 800
    ]
    if not short_pause_runs:
        raise ValueError("diagnostic WAV has no verified interior short PCM pause")
    voiced_median = _percentile(nonzero, 0.5)
    peak = max(envelope)
    if peak < max(0.02, voiced_median * 1.5):
        raise ValueError("diagnostic WAV has no verified strong syllable peak")
    return {
        "schema_version": "1.0",
        "path": str(resolved),
        "sha256": _sha256(resolved),
        "window_ms": window_ms,
        "windows_analyzed": len(envelope),
        "silence": {
            "start_seconds": silence_start * window_ms / 1_000,
            "duration_seconds": 2.0,
            "exact_neutral_window_ratio": exact_ratio,
            "maximum_rms": -negative_max_rms,
        },
        "speech": {
            "start_seconds": speech_start * window_ms / 1_000,
            "duration_seconds": 2.0,
            "speech_threshold": speech_threshold,
            "voiced_window_ratio": voiced_ratio,
            "mean_rms": speech_mean,
        },
        "short_pauses": [
            {
                "start_seconds": start * window_ms / 1_000,
                "duration_ms": (end - start) * window_ms,
                "exact_neutral": True,
            }
            for start, end in short_pause_runs
        ],
        "strong_syllable": {
            "timestamp_seconds": envelope.index(peak) * window_ms / 1_000,
            "peak_rms": peak,
            "voiced_median_rms": voiced_median,
            "peak_to_median_ratio": peak / max(voiced_median, 1e-9),
        },
        "passed": True,
    }


def _best_speech_source_window(
    envelope: list[float],
    *,
    window_count: int,
) -> tuple[int, dict[str, float]]:
    if len(envelope) < window_count:
        raise ValueError("source WAV is too short for a continuous speech section")
    nonzero = [value for value in envelope if value > 0.000_01]
    if not nonzero:
        raise ValueError("source WAV has no audible speech")
    speech_threshold = max(0.003, _percentile(nonzero, 0.2) * 0.55)
    best: tuple[float, int, float, float] | None = None
    for start in range(0, len(envelope) - window_count + 1):
        values = envelope[start : start + window_count]
        voiced_ratio = sum(value >= speech_threshold for value in values) / len(values)
        mean = sum(values) / len(values)
        score = voiced_ratio * 2 + mean
        candidate = (score, -start, voiced_ratio, mean)
        if best is None or candidate > best:
            best = candidate
    assert best is not None
    _, negative_start, voiced_ratio, mean = best
    if voiced_ratio < 0.7 or mean < 0.005:
        raise ValueError(
            "source WAV does not contain a sufficiently continuous speech section"
        )
    return -negative_start, {
        "speech_threshold": speech_threshold,
        "voiced_ratio": voiced_ratio,
        "mean_rms": mean,
    }


def _prepare_diagnostic_wav(
    source: Path,
    target: Path,
    *,
    duration_ms: int,
) -> dict[str, Any]:
    """Build one deterministic, auditable PCM stimulus shared by every A/B mode."""

    with wave.open(str(source), "rb") as reader:
        if reader.getcomptype() != "NONE":
            raise ValueError("diagnostic input must be uncompressed PCM WAV")
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        source_frames = reader.getnframes()
        pcm = reader.readframes(source_frames)
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    target_frames = round(sample_rate * duration_ms / 1_000)
    minimum_frames = sample_rate * 12
    if target_frames < minimum_frames:
        raise ValueError("diagnostic WAV must be at least twelve seconds")
    frame_size = channels * sample_width
    envelope, envelope_window_frames = _wave_envelope(
        pcm,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    continuous_frames = min(round(sample_rate * 3.0), target_frames - minimum_frames // 2)
    continuous_windows = max(1, continuous_frames // envelope_window_frames)
    speech_window, speech_evidence = _best_speech_source_window(
        envelope,
        window_count=continuous_windows,
    )
    speech_start_frame = speech_window * envelope_window_frames
    strong_window = max(range(len(envelope)), key=envelope.__getitem__)
    strong_frames = round(sample_rate * 0.8)
    strong_start_frame = max(
        0,
        min(
            source_frames - strong_frames,
            strong_window * envelope_window_frames - strong_frames // 2,
        ),
    )
    long_silence_frames = sample_rate * 2
    short_pause_frames = round(sample_rate * 0.3)
    fixed_frames = long_silence_frames + continuous_frames + short_pause_frames + strong_frames
    if fixed_frames > target_frames:
        raise ValueError("duration is too short for the required diagnostic sections")
    filler_frames = target_frames - fixed_frames
    sections: list[tuple[str, bytes, dict[str, Any]]] = [
        (
            "long_pcm_silence",
            _silence_bytes(
                long_silence_frames,
                channels=channels,
                sample_width=sample_width,
            ),
            {"source": "generated_pcm_neutral", "required_minimum_ms": 2_000},
        ),
        (
            "continuous_speech",
            _cyclic_pcm_slice(
                pcm,
                frame_size=frame_size,
                start_frame=speech_start_frame,
                frame_count=continuous_frames,
            ),
            {
                "source": "source_wav",
                "source_start_frame": speech_start_frame,
                **speech_evidence,
            },
        ),
        (
            "short_pcm_pause",
            _silence_bytes(
                short_pause_frames,
                channels=channels,
                sample_width=sample_width,
            ),
            {
                "source": "generated_pcm_neutral",
                "required_range_ms": [100, 800],
            },
        ),
        (
            "strong_syllable",
            _cyclic_pcm_slice(
                pcm,
                frame_size=frame_size,
                start_frame=strong_start_frame,
                frame_count=strong_frames,
            ),
            {
                "source": "source_wav",
                "source_start_frame": strong_start_frame,
                "source_peak_rms": envelope[strong_window],
            },
        ),
        (
            "natural_speech_remainder",
            _cyclic_pcm_slice(
                pcm,
                frame_size=frame_size,
                start_frame=speech_start_frame + continuous_frames,
                frame_count=filler_frames,
            ),
            {"source": "source_wav"},
        ),
    ]
    output_pcm = b"".join(section[1] for section in sections)
    if len(output_pcm) != target_frames * frame_size:
        raise RuntimeError("diagnostic PCM assembly produced an unexpected length")
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        writer.writeframes(output_pcm)
    section_audit: list[dict[str, Any]] = []
    frame_cursor = 0
    for name, section_pcm, metadata in sections:
        section_frames = len(section_pcm) // frame_size
        section_audit.append(
            {
                "kind": name,
                "start_ms": round(frame_cursor * 1_000 / sample_rate, 3),
                "end_ms": round((frame_cursor + section_frames) * 1_000 / sample_rate, 3),
                "frames": section_frames,
                "pcm_sha256": hashlib.sha256(section_pcm).hexdigest(),
                **metadata,
            }
        )
        frame_cursor += section_frames
    audit = {
        "schema_version": "1.0",
        "source": str(source),
        "source_sha256": _sha256(source),
        "path": str(target.resolve()),
        "sha256": _sha256(target),
        "duration_ms": round(target_frames * 1_000 / sample_rate),
        "sample_rate": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "pcm_frames": target_frames,
        "sections": section_audit,
    }
    audit["signal_validation"] = _scan_diagnostic_signal(target)
    return audit


def _select_audio_windows(audio_path: Path) -> dict[str, dict[str, Any]]:
    signal = _scan_diagnostic_signal(audio_path)
    return {
        "silence": {
            "start_seconds": signal["silence"]["start_seconds"],
            "selector": "minimum_rms_exact_pcm_window_scan",
            "evidence": signal["silence"],
            "audio_sha256": signal["sha256"],
        },
        "speech": {
            "start_seconds": signal["speech"]["start_seconds"],
            "selector": "maximum_voiced_ratio_envelope_window_scan",
            "evidence": signal["speech"],
            "audio_sha256": signal["sha256"],
        },
    }


def _transition_window(trace_path: Path, *, fps: int) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) < fps * 2:
        raise RuntimeError("trace is too short for a two-second transition window")
    candidates: list[dict[str, Any]] = []
    for index in range(1, len(rows)):
        before_motion = rows[index - 1]["motion_state"]
        after_motion = rows[index]["motion_state"]
        before_motion_index = rows[index - 1].get("motion_index")
        after_motion_index = rows[index].get("motion_index")
        before_blink = rows[index - 1]["blink_state"]
        after_blink = rows[index]["blink_state"]
        changes: list[dict[str, str]] = []
        if after_motion != before_motion:
            changes.append(
                {"track": "motion_state", "before": before_motion, "after": after_motion}
            )
        if after_motion_index != before_motion_index:
            changes.append(
                {
                    "track": "motion_index",
                    "before": str(before_motion_index),
                    "after": str(after_motion_index),
                }
            )
        if after_blink != before_blink:
            changes.append(
                {"track": "blink_state", "before": before_blink, "after": after_blink}
            )
        if not changes:
            continue
        timestamp = float(rows[index]["timestamp_ms"]) / 1_000
        max_start = max(0.0, float(rows[-1]["timestamp_ms"]) / 1_000 - 2.0)
        start = min(max(0.0, timestamp - 1.0), max_start)
        margin = min(timestamp - start, start + 2.0 - timestamp)
        candidates.append(
            {
                "start_seconds": start,
                "selector": "trace_state_change_centered",
                "transition_timestamp_seconds": timestamp,
                "changes": changes,
                "margin_seconds": margin,
                "trace_row": index,
            }
        )
    if not candidates:
        raise RuntimeError("trace contains no observable motion or blink state transition")
    selected = max(
        candidates,
        key=lambda candidate: (
            candidate["margin_seconds"],
            any(
                change["track"] in {"motion_state", "motion_index"}
                for change in candidate["changes"]
            ),
            -candidate["transition_timestamp_seconds"],
        ),
    )
    if not (
        selected["start_seconds"]
        <= selected["transition_timestamp_seconds"]
        <= selected["start_seconds"] + 2.0
    ):
        raise RuntimeError("selected transition is outside its evidence window")
    selected["trace_sha256"] = _sha256(trace_path)
    return selected


def _extract_sequence(
    *,
    ffmpeg: Path,
    video: Path,
    target: Path,
    start_seconds: float,
    fps: int,
) -> dict[str, object]:
    frames = target / "frames"
    frames.mkdir(parents=True, exist_ok=False)
    _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start_seconds:.6f}",
            "-i",
            str(video),
            "-t",
            "2",
            "-vf",
            f"fps={fps}",
            str(frames / "frame-%03d.png"),
        ],
        cwd=target,
    )
    frame_paths = sorted(frames.glob("frame-*.png"))
    if len(frame_paths) < fps * 2:
        raise RuntimeError(f"dynamic sequence is too short: {target}")
    filters = {
        "full": "scale=128:128",
        "face": "crop=280:250:220:15,scale=185:165",
        "eyes": "crop=240:110:240:65,scale=256:117",
    }
    contacts: dict[str, str] = {}
    for name, transform in filters.items():
        contact = target / f"{name}-contact.png"
        _run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(fps),
                "-start_number",
                "1",
                "-i",
                str(frames / "frame-%03d.png"),
                "-vf",
                f"{transform},tile=10x6:padding=2:margin=2",
                "-frames:v",
                "1",
                str(contact),
            ],
            cwd=target,
        )
        contacts[name] = str(contact.resolve())
    return {
        "start_seconds": round(start_seconds, 6),
        "duration_seconds": 2,
        "frames": [str(path.resolve()) for path in frame_paths],
        "contacts": contacts,
    }


def _extract_uniform_contact(
    *,
    ffmpeg: Path,
    video: Path,
    output: Path,
    duration_seconds: float,
) -> None:
    _run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            (
                f"fps=20/{duration_seconds:.6f},scale=256:256,"
                "tile=5x4:padding=4:margin=4"
            ),
            "-frames:v",
            "1",
            str(output),
        ],
        cwd=output.parent,
    )


def main() -> int:
    args = _parser().parse_args()
    model = args.model.expanduser().resolve(strict=True)
    audio = args.audio.expanduser().resolve(strict=True)
    live2d_python = args.live2d_python.expanduser().resolve(strict=True)
    ffmpeg = args.ffmpeg.expanduser().resolve(strict=True)
    if args.duration_ms < 12_000:
        raise ValueError("all isolation experiments require at least twelve seconds")
    source_audio_duration = _audio_duration_ms(audio)
    commit = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=WORKSPACE,
        timeout=30,
    ).stdout.strip()
    started = datetime.now(UTC)
    output_root = (
        args.output_root.expanduser().resolve()
        if args.output_root is not None
        else (
            WORKSPACE
            / "outputs"
            / "live2d-audit"
            / f"{started:%Y%m%dT%H%M%SZ}-{commit[:8]}"
        ).resolve()
    )
    output_root.mkdir(parents=True, exist_ok=False)
    diagnostic_audio = output_root / "diagnostic-input.wav"
    audio_audit = _prepare_diagnostic_wav(
        audio,
        diagnostic_audio,
        duration_ms=args.duration_ms,
    )
    audio_audit["source_duration_ms"] = source_audio_duration
    audio_audit_path = output_root / "diagnostic-input-audit.json"
    audio_audit_path.write_text(
        json.dumps(audio_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    audio_windows = _select_audio_windows(diagnostic_audio)
    modes = (*(("legacy_conflict",) if args.include_legacy else ()), *MODES)
    results: dict[str, object] = {}
    commands: list[list[str]] = []
    duration_seconds = args.duration_ms / 1_000
    for mode in modes:
        mode_root = output_root / mode
        mode_root.mkdir()
        transparent = mode_root / f"{mode}-transparent.webm"
        trace = mode_root / f"{mode}-trace.jsonl"
        diagnostic_path = mode_root / f"{mode}-diagnostics.json"
        command = [
            str(live2d_python),
            str(WORKSPACE / "scripts" / "render_live2d_host.py"),
            "--model",
            str(model),
            "--audio",
            str(diagnostic_audio),
            "--output",
            str(transparent),
            "--diagnostic-trace",
            str(trace),
            "--emotion",
            args.emotion,
            "--duration-ms",
            str(args.duration_ms),
            "--width",
            str(args.width),
            "--height",
            str(args.height),
            "--fps",
            str(args.fps),
            "--control-mode",
            mode,
            "--seed",
            str(args.seed),
        ]
        commands.append(command)
        rendered = _run(command, cwd=WORKSPACE)
        diagnostic_path.write_text(rendered.stdout, encoding="utf-8")
        diagnostics = json.loads(rendered.stdout)
        background = mode_root / f"{mode}-background.mp4"
        composite_command = [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(transparent),
            "-i",
            str(diagnostic_audio),
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x24302a:s={args.width}x{args.height}:r={args.fps}",
            "-filter_complex",
            "[2:v][0:v]overlay=shortest=1:format=auto,format=yuv420p[out]",
            "-map",
            "[out]",
            "-map",
            "1:a",
            "-c:v",
            "h264_mf",
            "-b:v",
            "4M",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(background),
        ]
        commands.append(composite_command)
        _run(composite_command, cwd=mode_root)
        transparent_analysis = mode_root / "transparent-analysis.json"
        background_analysis = mode_root / "background-analysis.json"
        for input_video, analysis in (
            (transparent, transparent_analysis),
            (background, background_analysis),
        ):
            analysis_command = [
                str(live2d_python),
                str(WORKSPACE / "scripts" / "analyze_live2d_video.py"),
                "--input",
                str(input_video),
                "--output",
                str(analysis),
                "--expected-fps",
                str(args.fps),
            ]
            if input_video == transparent:
                analysis_command.extend(
                    [
                        "--preencode-trace",
                        str(trace),
                        "--require-transparency",
                    ]
                )
            else:
                analysis_command.extend(
                    ["--quality-profile", "fixed_background"]
                )
            commands.append(analysis_command)
            _run(analysis_command, cwd=WORKSPACE)
        uniform_contact = mode_root / "uniform-20-contact.png"
        _extract_uniform_contact(
            ffmpeg=ffmpeg,
            video=background,
            output=uniform_contact,
            duration_seconds=duration_seconds,
        )
        transition_evidence = _transition_window(trace, fps=args.fps)
        sequence_windows = {
            **audio_windows,
            "transition": transition_evidence,
        }
        sequences = {}
        for name, window in sequence_windows.items():
            sequence = _extract_sequence(
                ffmpeg=ffmpeg,
                video=background,
                target=mode_root / f"sequence-{name}",
                start_seconds=float(window["start_seconds"]),
                fps=args.fps,
            )
            sequence["selection"] = window
            sequences[name] = sequence
        transparent_report = json.loads(transparent_analysis.read_text(encoding="utf-8"))
        background_report = json.loads(background_analysis.read_text(encoding="utf-8"))
        alpha_validation = transparent_report.get("alpha_validation")
        if not isinstance(alpha_validation, dict) or not alpha_validation.get("passed"):
            raise RuntimeError(f"transparency evidence gate failed for {mode}")
        results[mode] = {
            "transparent_webm": str(transparent.resolve()),
            "background_mp4": str(background.resolve()),
            "trace_jsonl": str(trace.resolve()),
            "diagnostics_json": str(diagnostic_path.resolve()),
            "transparent_analysis_json": str(transparent_analysis.resolve()),
            "background_analysis_json": str(background_analysis.resolve()),
            "uniform_contact_sheet": str(uniform_contact.resolve()),
            "sequences": sequences,
            "alpha_validation": alpha_validation,
            "quality_gate_passed": diagnostics["quality_gate_passed"],
            "gate_findings": diagnostics["gate_findings"],
            "decoded_quality": {
                "transparent": {
                    "passed": transparent_report["quality_gate_passed"],
                    "findings": transparent_report["gate_findings"],
                },
                "fixed_background": {
                    "passed": background_report["quality_gate_passed"],
                    "findings": background_report["gate_findings"],
                },
            },
        }
    comparison = output_root / "four-mode-comparison.mp4"
    comparison_inputs: list[str] = []
    for mode in MODES:
        comparison_inputs.extend(["-i", str(Path(results[mode]["background_mp4"]))])  # type: ignore[index]
    comparison_command = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *comparison_inputs,
        "-filter_complex",
        (
            "[0:v]scale=512:512[v0];[1:v]scale=512:512[v1];"
            "[2:v]scale=512:512[v2];[3:v]scale=512:512[v3];"
            "[v0][v1]hstack=inputs=2[top];[v2][v3]hstack=inputs=2[bottom];"
            "[top][bottom]vstack=inputs=2,format=yuv420p[out]"
        ),
        "-map",
        "[out]",
        "-map",
        "3:a",
        "-c:v",
        "h264_mf",
        "-b:v",
        "8M",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(comparison),
    ]
    commands.append(comparison_command)
    _run(comparison_command, cwd=output_root)
    required_candidate_modes = ("procedural_only", "no_lip_sync", "final")
    acceptance_failures: list[str] = []
    for mode in required_candidate_modes:
        result = results[mode]
        if not result["quality_gate_passed"]:
            acceptance_failures.append(f"{mode}:parameter_or_preencode_image_gate")
        decoded_quality = result["decoded_quality"]
        if not decoded_quality["transparent"]["passed"]:  # type: ignore[index]
            acceptance_failures.append(f"{mode}:decoded_transparent_gate")
        if not decoded_quality["fixed_background"]["passed"]:  # type: ignore[index]
            acceptance_failures.append(f"{mode}:decoded_background_gate")
    if args.include_legacy and results["legacy_conflict"]["quality_gate_passed"]:
        acceptance_failures.append("legacy_conflict:failed_to_reproduce")
    report = {
        "schema_version": "1.0",
        "commit": commit,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "model": {
            "path": str(model),
            "sha256": _sha256(model),
        },
        "audio": {
            "path": str(diagnostic_audio.resolve()),
            "sha256": _sha256(diagnostic_audio),
            "duration_ms": audio_audit["duration_ms"],
            "audit_json": str(audio_audit_path.resolve()),
            "source_path": str(audio),
            "source_sha256": _sha256(audio),
            "source_duration_ms": source_audio_duration,
            "required_sections": audio_audit["sections"],
            "signal_validation": audio_audit["signal_validation"],
        },
        "settings": {
            "width": args.width,
            "height": args.height,
            "fps": args.fps,
            "emotion": args.emotion,
            "seed": args.seed,
        },
        "quadrants": {
            "top_left": "motion_only",
            "top_right": "procedural_only",
            "bottom_left": "no_lip_sync",
            "bottom_right": "final",
        },
        "comparison_video": str(comparison.resolve()),
        "acceptance": {
            "passed": not acceptance_failures,
            "required_candidate_modes": list(required_candidate_modes),
            "failures": acceptance_failures,
        },
        "results": results,
        "commands": commands,
    }
    report_path = output_root / "experiment-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output_root": str(output_root),
                "report": str(report_path),
                "comparison_video": str(comparison),
            },
            ensure_ascii=False,
        )
    )
    if acceptance_failures:
        raise RuntimeError(
            "Live2D A/B acceptance failed: " + ", ".join(acceptance_failures)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
