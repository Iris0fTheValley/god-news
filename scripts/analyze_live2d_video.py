from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "src"))
sys.path.insert(0, str(WORKSPACE / "scripts"))

from render_live2d_host import _frame_image_metrics  # noqa: E402

from god_news.live2d_diagnostics import (  # noqa: E402
    IMAGE_REQUIRED_TRACKS,
    evaluate_image_tracks,
    pairwise,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure decoded Live2D frame continuity and image-space jitter."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-fps", type=int, default=30)
    parser.add_argument("--preencode-trace", type=Path)
    parser.add_argument("--require-transparency", action="store_true")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument(
        "--crop-normalized",
        type=float,
        nargs=4,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="Analyze only this normalized input-frame rectangle.",
    )
    parser.add_argument("--require-dynamic-quality", action="store_true")
    parser.add_argument(
        "--quality-profile",
        choices=("host_source", "final_composite"),
        default="host_source",
    )
    return parser


def _normalized_crop_bounds(
    frame_width: int,
    frame_height: int,
    crop: tuple[float, float, float, float] | None,
) -> tuple[int, int, int, int]:
    if crop is None:
        return 0, 0, frame_width, frame_height
    x, y, width, height = crop
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > 1
        or y + height > 1
    ):
        raise ValueError("normalized crop must be positive and stay inside the frame")
    left = max(0, min(frame_width - 1, math.floor(x * frame_width)))
    top = max(0, min(frame_height - 1, math.floor(y * frame_height)))
    right = max(left + 1, min(frame_width, math.ceil((x + width) * frame_width)))
    bottom = max(top + 1, min(frame_height, math.ceil((y + height) * frame_height)))
    return left, top, right, bottom


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _preencoded_alpha_evidence(trace_path: Path) -> dict[str, Any]:
    resolved = trace_path.expanduser().resolve(strict=True)
    rows = [
        json.loads(line)
        for line in resolved.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ratios = [
        float(row["image"]["alpha_area_ratio"])
        for row in rows
        if isinstance(row.get("image"), dict)
        and row["image"].get("alpha_area_ratio") is not None
    ]
    minimum = min(ratios) if ratios else 0.0
    maximum = max(ratios) if ratios else 0.0
    mean = sum(ratios) / len(ratios) if ratios else 0.0
    # The renderer measured foreground alpha coverage before VP9 encoding. A full
    # opaque canvas has coverage 1.0, while a missing model has coverage 0.0.
    passed = len(ratios) == len(rows) and len(ratios) > 1 and 0.001 < mean < 0.95
    return {
        "passed": passed,
        "trace_path": str(resolved),
        "trace_sha256": _sha256(resolved),
        "trace_rows": len(rows),
        "measured_rows": len(ratios),
        "alpha_area_ratio_min": minimum,
        "alpha_area_ratio_max": maximum,
        "alpha_area_ratio_mean": mean,
        "criterion": "all rows measured and 0.001 < mean foreground coverage < 0.95",
    }


def _browser_alpha_probe(
    video: Path,
    *,
    output_dir: Path,
    node: Path | None,
    browser_channel: str,
) -> dict[str, Any]:
    node_path = str(node) if node is not None else shutil.which("node")
    if not node_path:
        raise RuntimeError("Node.js is required for the browser transparency probe")
    frontend = WORKSPACE / "frontend"
    if not (frontend / "node_modules" / "@playwright" / "test").exists():
        raise RuntimeError("frontend Playwright dependency is not installed")
    output_dir.mkdir(parents=True, exist_ok=True)
    script = output_dir / "browser-alpha-probe.mjs"
    result_path = output_dir / "browser-alpha-probe.json"
    html_path = output_dir / "browser-alpha-probe.html"
    html_path.write_text(
        "<!doctype html><meta charset=utf-8><title>alpha probe</title>"
        '<video id="video" muted playsinline preload="auto" '
        'src="/video"></video>',
        encoding="utf-8",
    )
    script.write_text(
        r"""
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

const require = createRequire(pathToFileURL(path.join(process.cwd(), 'package.json')));
const {chromium} = require('@playwright/test');
const [htmlPath, videoPath, outputPath, channel, artifactDir] = process.argv.slice(2);
const server = http.createServer((request, response) => {
  if (request.url === '/') {
    const html = fs.readFileSync(htmlPath);
    response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
    response.end(html);
    return;
  }
  if (request.url !== '/video') {
    response.writeHead(404).end();
    return;
  }
  const stat = fs.statSync(videoPath);
  const range = request.headers.range;
  response.setHeader('Content-Type', 'video/webm');
  response.setHeader('Accept-Ranges', 'bytes');
  if (!range) {
    response.writeHead(200, {'Content-Length': stat.size});
    fs.createReadStream(videoPath).pipe(response);
    return;
  }
  const match = /^bytes=(\d+)-(\d*)$/.exec(range);
  if (!match) {
    response.writeHead(416).end();
    return;
  }
  const start = Number(match[1]);
  const end = match[2] ? Number(match[2]) : stat.size - 1;
  response.writeHead(206, {
    'Content-Length': end - start + 1,
    'Content-Range': `bytes ${start}-${end}/${stat.size}`,
  });
  fs.createReadStream(videoPath, {start, end}).pipe(response);
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const address = server.address();
let browser;
let launchMode = channel;
try {
  browser = await chromium.launch({headless: true, channel});
} catch (error) {
  launchMode = 'bundled-chromium-fallback';
  browser = await chromium.launch({headless: true});
}
try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${address.port}/`);
  const result = await page.evaluate(async () => {
    const video = document.querySelector('#video');
    await new Promise((resolve, reject) => {
      if (video.readyState >= 2) return resolve();
      video.addEventListener('loadeddata', resolve, {once: true});
      video.addEventListener(
        'error',
        () => reject(new Error(video.error?.message || 'video load failed')),
        {once: true},
      );
    });
    const duration = video.duration;
    if (!Number.isFinite(duration) || duration < 1) throw new Error('invalid video duration');
    const times = [Math.min(0.25, duration / 4), duration / 2, Math.max(0, duration - 0.25)];
    const samples = [];
    const captures = [];
    for (const timestamp of times) {
      video.currentTime = timestamp;
      await new Promise((resolve, reject) => {
        video.addEventListener('seeked', resolve, {once: true});
        video.addEventListener('error', () => reject(new Error('seek failed')), {once: true});
      });
      const width = video.videoWidth;
      const height = video.videoHeight;
      const render = (value) => {
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext('2d', {willReadFrequently: true});
        context.fillStyle = `rgb(${value},${value},${value})`;
        context.fillRect(0, 0, width, height);
        context.drawImage(video, 0, 0, width, height);
        return {canvas, data: context.getImageData(0, 0, width, height).data};
      };
      const black = render(0);
      const white = render(255);
      const differences = [];
      let transparent = 0;
      let opaque = 0;
      for (let index = 0; index < black.data.length; index += 4) {
        const delta = (
          Math.abs(white.data[index] - black.data[index]) +
          Math.abs(white.data[index + 1] - black.data[index + 1]) +
          Math.abs(white.data[index + 2] - black.data[index + 2])
        ) / 3;
        differences.push(delta);
        if (delta >= 200) transparent += 1;
        if (delta <= 20) opaque += 1;
      }
      differences.sort((left, right) => left - right);
      const pixelCount = differences.length;
      const quantile = (fraction) => differences[Math.floor((pixelCount - 1) * fraction)];
      samples.push({
        timestamp_seconds: timestamp,
        width,
        height,
        transparent_pixel_ratio: transparent / pixelCount,
        opaque_pixel_ratio: opaque / pixelCount,
        background_delta_p05: quantile(0.05),
        background_delta_p50: quantile(0.5),
        background_delta_p95: quantile(0.95),
      });
      if (captures.length === 0 || timestamp === times[1]) {
        captures.push({
          black: black.canvas.toDataURL('image/png'),
          white: white.canvas.toDataURL('image/png'),
        });
      }
    }
    return {duration_seconds: duration, samples, captures};
  });
  const capture = result.captures[result.captures.length - 1];
  for (const [name, value] of Object.entries(capture)) {
    fs.writeFileSync(
      path.join(artifactDir, `composited-${name}.png`),
      Buffer.from(value.split(',')[1], 'base64'),
    );
  }
  delete result.captures;
  result.browser_launch_mode = launchMode;
  result.user_agent = await page.evaluate(() => navigator.userAgent);
  result.passed = result.samples.every((sample) =>
    sample.transparent_pixel_ratio > 0.05 &&
    sample.opaque_pixel_ratio > 0.01 &&
    sample.background_delta_p05 < 20 &&
    sample.background_delta_p95 > 200
  );
  result.criterion = [
    'each browser-decoded frame must contain both background-responsive',
    'transparent pixels and background-invariant opaque pixels',
  ].join(' ');
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf8');
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            node_path,
            str(script),
            str(html_path),
            str(video),
            str(result_path),
            browser_channel,
            str(output_dir),
        ],
        cwd=frontend,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        creationflags=0x08000000 | 0x00000200,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "browser transparency probe failed: "
            + (completed.stderr or completed.stdout)[-4_000:]
        )
    report = json.loads(result_path.read_text(encoding="utf-8"))
    report["report_path"] = str(result_path.resolve())
    report["black_composite_png"] = str((output_dir / "composited-black.png").resolve())
    report["white_composite_png"] = str((output_dir / "composited-white.png").resolve())
    return report


def analyze(
    path: Path,
    *,
    expected_fps: int,
    preencode_trace: Path | None = None,
    require_transparency: bool = False,
    alpha_artifact_dir: Path | None = None,
    node: Path | None = None,
    browser_channel: str = "msedge",
    start_seconds: float = 0.0,
    duration_seconds: float | None = None,
    crop_normalized: tuple[float, float, float, float] | None = None,
    quality_profile: str = "host_source",
) -> dict[str, object]:
    import av
    import numpy as np

    resolved = path.expanduser().resolve(strict=True)
    if expected_fps < 1:
        raise ValueError("expected-fps must be positive")
    if start_seconds < 0 or (duration_seconds is not None and duration_seconds <= 0):
        raise ValueError("analysis window must have non-negative start and positive duration")
    tracks: dict[str, list[float]] = {key: [] for key in IMAGE_REQUIRED_TRACKS}
    timestamps: list[float] = []
    frame_hashes: list[str] = []
    previous = None
    alpha_source = "decoded"
    crop_pixels: tuple[int, int, int, int] | None = None
    with av.open(str(resolved)) as container:
        stream = container.streams.video[0]
        for index, frame in enumerate(container.decode(stream)):
            timestamp = (
                float(frame.time)
                if frame.time is not None
                else index / expected_fps
            )
            if timestamp + 1e-9 < start_seconds:
                continue
            if (
                duration_seconds is not None
                and timestamp >= start_seconds + duration_seconds - 1e-9
            ):
                break
            rgba = frame.to_ndarray(format="rgba")
            if crop_pixels is None:
                crop_pixels = _normalized_crop_bounds(
                    rgba.shape[1], rgba.shape[0], crop_normalized
                )
            left, top, right, bottom = crop_pixels
            rgba = rgba[top:bottom, left:right]
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
            timestamps.append(timestamp)
            frame_hashes.append(hashlib.sha256(rgba.tobytes()).hexdigest())
        average_rate = float(stream.average_rate) if stream.average_rate else 0.0
        width = stream.width
        height = stream.height
        codec = stream.codec_context.name
        pixel_format = stream.codec_context.format.name
        stream_metadata = dict(stream.metadata)
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
    image_metric_objects, image_limits, image_findings = evaluate_image_tracks(
        tracks,
        timestamps,
        fps=expected_fps,
        frame_width=crop_pixels[2] - crop_pixels[0],
        frame_height=crop_pixels[3] - crop_pixels[1],
        quality_profile=quality_profile,
    )
    metric_summary = {
        name: metrics.as_dict()
        for name, metrics in image_metric_objects.items()
    }
    deltas = [right - left for left, right in pairwise(timestamps)]
    report: dict[str, object] = {
        "schema_version": "1.0",
        "input": str(resolved),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "size_bytes": resolved.stat().st_size,
        "frames": len(frame_hashes),
        "width": width,
        "height": height,
        "codec": codec,
        "pixel_format": pixel_format,
        "stream_metadata": stream_metadata,
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
        "image_thresholds": image_limits,
        "gate_findings": [finding.as_dict() for finding in image_findings],
        "quality_gate_passed": not image_findings,
        "analysis_window": {
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
        },
        "analysis_region": {
            "normalized": list(crop_normalized) if crop_normalized is not None else None,
            "pixels": {
                "left": crop_pixels[0],
                "top": crop_pixels[1],
                "right": crop_pixels[2],
                "bottom": crop_pixels[3],
            },
        },
        "quality_profile": quality_profile,
    }
    if preencode_trace is not None or require_transparency:
        if preencode_trace is None:
            raise ValueError("require-transparency needs --preencode-trace evidence")
        alpha_mode = stream_metadata.get("alpha_mode") or stream_metadata.get(
            "ALPHA_MODE"
        )
        container_evidence = {
            "passed": str(alpha_mode) == "1",
            "alpha_mode": alpha_mode,
            "criterion": "WebM video stream metadata alpha_mode must equal 1",
        }
        artifacts = (
            alpha_artifact_dir.expanduser().resolve()
            if alpha_artifact_dir is not None
            else resolved.parent / f"{resolved.stem}-alpha-probe"
        )
        preencoded_evidence = _preencoded_alpha_evidence(preencode_trace)
        browser_evidence = _browser_alpha_probe(
            resolved,
            output_dir=artifacts,
            node=node,
            browser_channel=browser_channel,
        )
        alpha_validation = {
            "passed": all(
                evidence["passed"]
                for evidence in (
                    container_evidence,
                    preencoded_evidence,
                    browser_evidence,
                )
            ),
            "container": container_evidence,
            "preencoded_renderer": preencoded_evidence,
            "browser_composite": browser_evidence,
            "decoded_alpha_source_is_not_proof": alpha_source,
        }
        report["alpha_validation"] = alpha_validation
        if require_transparency and not alpha_validation["passed"]:
            raise RuntimeError(
                "transparency evidence gate failed: "
                + json.dumps(alpha_validation, ensure_ascii=False)
            )
    return report


def main() -> int:
    args = _parser().parse_args()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = analyze(
        args.input,
        expected_fps=args.expected_fps,
        preencode_trace=args.preencode_trace,
        require_transparency=args.require_transparency,
        alpha_artifact_dir=output.parent / f"{output.stem}-alpha-probe",
        node=args.node,
        browser_channel=args.browser_channel,
        start_seconds=args.start_seconds,
        duration_seconds=args.duration_seconds,
        crop_normalized=(
            tuple(args.crop_normalized) if args.crop_normalized is not None else None
        ),
        quality_profile=args.quality_profile,
    )
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    if args.require_dynamic_quality and not report["quality_gate_passed"]:
        raise RuntimeError(
            "decoded video failed its dynamic image quality gate: "
            + json.dumps(report["gate_findings"], ensure_ascii=False)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
