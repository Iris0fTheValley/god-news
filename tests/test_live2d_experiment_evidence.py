from __future__ import annotations

import hashlib
import json
import math
import sys
import wave
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "scripts"))

from analyze_live2d_video import _preencoded_alpha_evidence  # noqa: E402
from run_live2d_ab_experiments import (  # noqa: E402
    _prepare_diagnostic_wav,
    _select_audio_windows,
    _transition_window,
)


def _write_source_speech(path: Path, *, duration_seconds: float = 8.0) -> None:
    sample_rate = 16_000
    frames = bytearray()
    for index in range(round(sample_rate * duration_seconds)):
        timestamp = index / sample_rate
        # Audibly non-zero, varying speech-like carrier with one strong syllable.
        amplitude = 0.22 + 0.08 * math.sin(2 * math.pi * 2.1 * timestamp)
        if 3.0 <= timestamp < 3.25:
            amplitude = 0.8
        value = round(32_767 * amplitude * math.sin(2 * math.pi * 180 * timestamp))
        frames.extend(value.to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(bytes(frames))


def test_prepare_diagnostic_wav_has_auditable_required_sections(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    output = tmp_path / "diagnostic.wav"
    _write_source_speech(source)

    audit = _prepare_diagnostic_wav(source, output, duration_ms=12_500)

    assert output.is_file()
    assert audit["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert audit["duration_ms"] == 12_500
    sections = {section["kind"]: section for section in audit["sections"]}
    assert sections["long_pcm_silence"]["end_ms"] == 2_000
    assert sections["continuous_speech"]["voiced_ratio"] >= 0.7
    assert sections["short_pcm_pause"]["end_ms"] - sections["short_pcm_pause"]["start_ms"] == 300
    assert sections["strong_syllable"]["source_peak_rms"] > 0.4
    with wave.open(str(output), "rb") as reader:
        assert reader.readframes(reader.getframerate() * 2) == b"\0" * (16_000 * 2 * 2)

    assert audit["signal_validation"]["passed"] is True
    assert audit["signal_validation"]["short_pauses"]
    assert audit["signal_validation"]["strong_syllable"]["peak_to_median_ratio"] > 1.5

    windows = _select_audio_windows(output)
    assert windows["silence"]["start_seconds"] == 0
    assert 2 <= windows["speech"]["start_seconds"] <= 3
    assert windows["silence"]["selector"] == "minimum_rms_exact_pcm_window_scan"
    assert windows["speech"]["selector"] == "maximum_voiced_ratio_envelope_window_scan"


def test_prepare_diagnostic_wav_rejects_non_speech_source(tmp_path: Path) -> None:
    source = tmp_path / "silence.wav"
    with wave.open(str(source), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(b"\0" * 16_000 * 2 * 4)

    with pytest.raises(ValueError, match="no audible speech"):
        _prepare_diagnostic_wav(source, tmp_path / "output.wav", duration_ms=12_000)


def test_transition_window_is_selected_from_observed_state_change(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    rows = []
    for frame in range(120):
        rows.append(
            {
                "timestamp_ms": frame * 1_000 / 30,
                "motion_state": "idle" if frame < 70 else "entering_motion",
                "blink_state": "waiting",
            }
        )
    trace.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    selected = _transition_window(trace, fps=30)

    assert selected["selector"] == "trace_state_change_centered"
    assert selected["trace_row"] == 70
    assert selected["changes"] == [
        {"track": "motion_state", "before": "idle", "after": "entering_motion"}
    ]
    assert selected["start_seconds"] < selected["transition_timestamp_seconds"]
    assert selected["transition_timestamp_seconds"] < selected["start_seconds"] + 2


def test_transition_window_fails_when_trace_has_no_state_change(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp_ms": frame * 1_000 / 30,
                    "motion_state": "idle",
                    "blink_state": "waiting",
                }
            )
            for frame in range(90)
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="no observable"):
        _transition_window(trace, fps=30)


def test_transition_window_accepts_observed_motion_index_change(tmp_path: Path) -> None:
    trace = tmp_path / "legacy-trace.jsonl"
    rows = [
        {
            "timestamp_ms": frame * (1000 / 30),
            "motion_state": "legacy_immediate_restart",
            "motion_index": 0 if frame < 70 else 1,
            "blink_state": "legacy_periodic",
        }
        for frame in range(120)
    ]
    trace.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    selected = _transition_window(trace, fps=30)

    assert selected["transition_timestamp_seconds"] == pytest.approx(70 / 30)
    assert selected["changes"] == [
        {"track": "motion_index", "before": "0", "after": "1"}
    ]


def test_preencoded_alpha_evidence_is_fail_closed(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            json.dumps({"image": {"alpha_area_ratio": ratio}})
            for ratio in (0.31, 0.32, 0.33)
        ),
        encoding="utf-8",
    )
    evidence = _preencoded_alpha_evidence(trace)
    assert evidence["passed"] is True
    assert evidence["measured_rows"] == 3

    opaque = tmp_path / "opaque.jsonl"
    opaque.write_text(
        "\n".join(
            json.dumps({"image": {"alpha_area_ratio": 1.0}}) for _ in range(3)
        ),
        encoding="utf-8",
    )
    assert _preencoded_alpha_evidence(opaque)["passed"] is False

    missing = tmp_path / "missing.jsonl"
    missing.write_text(
        json.dumps({"image": {"alpha_area_ratio": 0.3}})
        + "\n"
        + json.dumps({"image": {}}),
        encoding="utf-8",
    )
    assert _preencoded_alpha_evidence(missing)["passed"] is False
