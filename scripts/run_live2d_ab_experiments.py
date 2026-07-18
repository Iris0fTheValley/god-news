from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import wave
from datetime import UTC, datetime
from pathlib import Path

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


def _transition_window(trace_path: Path, *, fps: int) -> float:
    rows = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    previous_state = rows[0]["motion_state"]
    for row in rows[1:]:
        state = row["motion_state"]
        if state != previous_state and state in {
            "exiting_motion",
            "returning_to_neutral",
            "closing",
        }:
            return max(0.0, float(row["timestamp_ms"]) / 1_000 - 1.0)
        previous_state = state
    for row in rows:
        if row["blink_state"] == "closing":
            return max(0.0, float(row["timestamp_ms"]) / 1_000 - 1.0)
    return max(0.0, len(rows) / fps / 2 - 1.0)


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
    actual_audio_duration = _audio_duration_ms(audio)
    if abs(actual_audio_duration - args.duration_ms) > 50:
        raise ValueError("duration-ms must match the PCM audio duration")
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
            str(audio),
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
            str(audio),
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
            commands.append(analysis_command)
            _run(analysis_command, cwd=WORKSPACE)
        uniform_contact = mode_root / "uniform-20-contact.png"
        _extract_uniform_contact(
            ffmpeg=ffmpeg,
            video=background,
            output=uniform_contact,
            duration_seconds=duration_seconds,
        )
        transition_start = _transition_window(trace, fps=args.fps)
        sequence_windows = {
            "silence": 0.0,
            "speech": 1.0,
            "transition": transition_start,
        }
        sequences = {
            name: _extract_sequence(
                ffmpeg=ffmpeg,
                video=background,
                target=mode_root / f"sequence-{name}",
                start_seconds=start,
                fps=args.fps,
            )
            for name, start in sequence_windows.items()
        }
        results[mode] = {
            "transparent_webm": str(transparent.resolve()),
            "background_mp4": str(background.resolve()),
            "trace_jsonl": str(trace.resolve()),
            "diagnostics_json": str(diagnostic_path.resolve()),
            "transparent_analysis_json": str(transparent_analysis.resolve()),
            "background_analysis_json": str(background_analysis.resolve()),
            "uniform_contact_sheet": str(uniform_contact.resolve()),
            "sequences": sequences,
            "quality_gate_passed": diagnostics["quality_gate_passed"],
            "gate_findings": diagnostics["gate_findings"],
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
            "path": str(audio),
            "sha256": _sha256(audio),
            "duration_ms": actual_audio_duration,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
