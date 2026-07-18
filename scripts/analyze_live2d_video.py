from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))
sys.path.insert(0, str(WORKSPACE / "scripts"))

from render_live2d_host import _frame_image_metrics  # noqa: E402

from god_news.live2d_diagnostics import compute_signal_metrics, pairwise  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure decoded Live2D frame continuity and image-space jitter."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-fps", type=int, default=30)
    return parser


def analyze(path: Path, *, expected_fps: int) -> dict[str, object]:
    import av
    import numpy as np

    resolved = path.expanduser().resolve(strict=True)
    if expected_fps < 1:
        raise ValueError("expected-fps must be positive")
    tracks: dict[str, list[float]] = {
        key: []
        for key in (
            "alpha_area_ratio",
            "centroid_x",
            "centroid_y",
            "perceptual_delta",
            "alpha_delta",
            "face_delta",
            "eye_delta",
        )
    }
    timestamps: list[float] = []
    frame_hashes: list[str] = []
    previous = None
    alpha_source = "decoded"
    with av.open(str(resolved)) as container:
        stream = container.streams.video[0]
        for index, frame in enumerate(container.decode(stream)):
            rgba = frame.to_ndarray(format="rgba")
            alpha = rgba[:, :, 3]
            if int(alpha.max()) - int(alpha.min()) <= 1:
                alpha_source = "recovered_from_background"
                corners = np.concatenate(
                    (
                        rgba[:8, :8, :3].reshape(-1, 3),
                        rgba[:8, -8:, :3].reshape(-1, 3),
                        rgba[-8:, :8, :3].reshape(-1, 3),
                        rgba[-8:, -8:, :3].reshape(-1, 3),
                    )
                )
                background = np.median(corners, axis=0)
                distance = np.sqrt(
                    np.sum(
                        (rgba[:, :, :3].astype(np.float32) - background) ** 2,
                        axis=2,
                    )
                )
                recovered = np.clip((distance - 4) / 24, 0, 1) * 255
                rgba = rgba.copy()
                rgba[:, :, 3] = recovered.astype(np.uint8)
            metrics = _frame_image_metrics(rgba, previous)
            previous = rgba
            for key, value in metrics.items():
                tracks[key].append(value)
            timestamp = (
                float(frame.time)
                if frame.time is not None
                else index / expected_fps
            )
            timestamps.append(timestamp)
            frame_hashes.append(hashlib.sha256(rgba.tobytes()).hexdigest())
        average_rate = float(stream.average_rate) if stream.average_rate else 0.0
        width = stream.width
        height = stream.height
        codec = stream.codec_context.name
        pixel_format = stream.codec_context.format.name
    if not timestamps:
        raise RuntimeError("video contains no decodable frames")
    if len(timestamps) == 1:
        timestamps.append(timestamps[0] + 1 / expected_fps)
        for values in tracks.values():
            values.append(values[-1])
        frame_hashes.append(frame_hashes[-1])
    duplicate_pairs = sum(
        frame_hashes[index] == frame_hashes[index - 1]
        for index in range(1, len(frame_hashes))
    )
    longest_duplicate_run = 0
    current_run = 0
    for index in range(1, len(frame_hashes)):
        if frame_hashes[index] == frame_hashes[index - 1]:
            current_run += 1
            longest_duplicate_run = max(longest_duplicate_run, current_run)
        else:
            current_run = 0
    metric_summary = {
        key: compute_signal_metrics(
            values,
            timestamps,
            reversal_epsilon=0.0001,
        ).as_dict()
        for key, values in tracks.items()
    }
    deltas = [right - left for left, right in pairwise(timestamps)]
    return {
        "schema_version": "1.0",
        "input": str(resolved),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "size_bytes": resolved.stat().st_size,
        "frames": len(frame_hashes),
        "width": width,
        "height": height,
        "codec": codec,
        "pixel_format": pixel_format,
        "alpha_source": alpha_source,
        "average_fps": average_rate,
        "timestamp_delta_ms_min": min(deltas) * 1_000 if deltas else 0.0,
        "timestamp_delta_ms_max": max(deltas) * 1_000 if deltas else 0.0,
        "timestamp_delta_ms_p95": (
            sorted(deltas)[math.floor((len(deltas) - 1) * 0.95)] * 1_000
            if deltas
            else 0.0
        ),
        "exact_duplicate_pair_ratio": duplicate_pairs / max(1, len(frame_hashes) - 1),
        "longest_exact_duplicate_run": longest_duplicate_run,
        "image_metrics": metric_summary,
    }


def main() -> int:
    args = _parser().parse_args()
    report = analyze(args.input, expected_fps=args.expected_fps)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
