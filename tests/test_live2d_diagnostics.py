from __future__ import annotations

import math

import pytest

from god_news.live2d_control import PARAM_ANGLE_X, ParameterRange
from god_news.live2d_diagnostics import (
    IMAGE_REQUIRED_TRACKS,
    compute_signal_metrics,
    evaluate_image_tracks,
    evaluate_signal,
    robust_audio_calibration,
    threshold_for_parameter,
)


def test_signal_metrics_distinguish_slow_motion_from_frame_reversal_jitter() -> None:
    timestamps = [index / 30 for index in range(180)]
    smooth = [math.sin(timestamp * 0.8) for timestamp in timestamps]
    jitter = [
        smooth[index] + (0.08 if index % 2 else -0.08)
        for index in range(len(smooth))
    ]

    smooth_metrics = compute_signal_metrics(
        smooth,
        timestamps,
        reversal_epsilon=0.001,
    )
    jitter_metrics = compute_signal_metrics(
        jitter,
        timestamps,
        reversal_epsilon=0.001,
    )

    assert jitter_metrics.direction_reversals_per_second > 20
    assert jitter_metrics.high_frequency_energy_ratio > 3
    assert jitter_metrics.alternating_energy_ratio > 0.9
    assert smooth_metrics.direction_reversals_per_second < 1
    assert smooth_metrics.high_frequency_energy_ratio < 0.1


def test_signal_metrics_require_strictly_monotonic_timestamps() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        compute_signal_metrics(
            [0, 1, 2],
            [0, 0.1, 0.1],
            reversal_epsilon=0.01,
        )


def test_parameter_threshold_is_derived_from_model_range_and_fps() -> None:
    parameter_range = ParameterRange(-30, 30, 0)
    at_30 = threshold_for_parameter(
        PARAM_ANGLE_X,
        parameter_range,
        fps=30,
    )
    at_60 = threshold_for_parameter(
        PARAM_ANGLE_X,
        parameter_range,
        fps=60,
    )

    assert at_30.maximum_absolute_step == pytest.approx(
        at_60.maximum_absolute_step * 2
    )
    assert at_30.maximum_absolute_velocity == at_60.maximum_absolute_velocity


def test_gate_reports_high_frequency_jitter() -> None:
    timestamps = [index / 30 for index in range(120)]
    values = [0.5 if index % 2 else -0.5 for index in range(120)]
    metrics = compute_signal_metrics(
        values,
        timestamps,
        reversal_epsilon=0.001,
    )
    threshold = threshold_for_parameter(
        PARAM_ANGLE_X,
        ParameterRange(-30, 30, 0),
        fps=30,
    )
    findings = evaluate_signal(PARAM_ANGLE_X, metrics, threshold)

    codes = {finding.metric for finding in findings}
    assert "direction_reversals_per_second" in codes
    assert "high_frequency_energy_ratio" in codes


def test_audio_calibration_uses_quiet_floor_and_robust_voiced_peak() -> None:
    envelope = [0.002] * 30 + [0.08] * 50 + [0.2] * 15 + [0.9]

    noise_floor, peak = robust_audio_calibration(envelope)

    assert 0.002 < noise_floor < 0.01
    assert 0.15 < peak < 0.3


def test_image_gate_rejects_every_frame_alternating_flicker() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["perceptual_delta"] = [0.0] + [0.3137255] * 59
    tracks["face_delta"] = [0.0] + [0.3137255] * 59
    tracks["eye_delta"] = [0.0] + [0.3137255] * 59
    alternating = [0.0] + [0.3137255 if index % 2 else -0.3137255 for index in range(1, 60)]
    tracks["face_signed_delta"] = alternating
    tracks["eye_signed_delta"] = alternating
    tracks["alpha_area_ratio"] = [
        0.5 + (0.05 if index % 2 else -0.05) for index in range(60)
    ]

    _, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    codes = {finding.code for finding in findings}
    assert "image_perceptual_delta_p99_direct_exceeded" in codes
    assert "image_face_signed_delta_period_two_exceeded" in codes
    assert "image_eye_signed_delta_period_two_exceeded" in codes
    assert "image_face_signed_delta_sustained_high_frequency_exceeded" in codes
    assert "image_eye_signed_delta_sustained_high_frequency_exceeded" in codes
    assert "image_alpha_area_ratio_period_two_exceeded" in codes


def test_final_composite_period_two_gate_requires_visible_amplitude() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["alpha_area_ratio"] = [
        0.3 + (0.002 if index % 2 else -0.002) for index in range(60)
    ]

    _, source_limits, source_findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=616, frame_height=676
    )
    _, final_limits, final_findings = evaluate_image_tracks(
        tracks,
        timestamps,
        fps=30,
        frame_width=616,
        frame_height=676,
        quality_profile="final_composite",
    )

    assert source_limits["geometry_period_two_min_p95_step"] == 0.002
    assert final_limits["geometry_period_two_min_p95_step"] == 0.005
    assert "image_alpha_area_ratio_period_two_exceeded" in {
        finding.code for finding in source_findings
    }
    assert "image_alpha_area_ratio_period_two_exceeded" not in {
        finding.code for finding in final_findings
    }


def test_image_signed_delta_high_frequency_requires_sustained_reversals() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    for start in (8, 28, 48):
        tracks["face_signed_delta"][start : start + 2] = [0.03, -0.03]

    metrics, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    assert metrics["face_signed_delta"].high_frequency_energy_ratio > 1.7
    assert metrics["face_signed_delta"].direction_reversals_per_second < 10
    assert "image_face_signed_delta_sustained_high_frequency_exceeded" not in {
        finding.code for finding in findings
    }


def test_image_signed_delta_gate_requires_temporally_sustained_fast_jitter() -> None:
    timestamps = [index / 30 for index in range(60)]

    def tracks_with_face_signal(signal: list[float]) -> dict[str, list[float]]:
        tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
        for name in (
            "alpha_area_ratio",
            "alpha_spread_x",
            "alpha_spread_y",
            "centroid_x",
            "centroid_y",
            "outline_centroid_x",
            "outline_centroid_y",
        ):
            tracks[name] = [0.5] * 60
        tracks["face_signed_delta"] = signal
        return tracks

    bounded_activity = [
        0.02 * math.sin(2 * math.pi * 12 * timestamp) if index < 30 else 0.0
        for index, timestamp in enumerate(timestamps)
    ]
    bounded_metrics, limits, bounded_findings = evaluate_image_tracks(
        tracks_with_face_signal(bounded_activity),
        timestamps,
        fps=30,
        frame_width=720,
        frame_height=720,
    )
    bounded_face = bounded_metrics["face_signed_delta"]
    assert bounded_face.high_frequency_energy_ratio > 1.7
    assert bounded_face.direction_reversals_per_second > 10
    assert limits["signed_delta_high_frequency_min_reversals"] == 10.0
    assert limits["signed_delta_high_frequency_min_window_coverage"] == 0.75
    assert "image_face_signed_delta_sustained_high_frequency_exceeded" not in {
        finding.code for finding in bounded_findings
    }

    fast_jitter = [
        0.02 * math.sin(2 * math.pi * 8 * timestamp) for timestamp in timestamps
    ]
    jitter_metrics, _, jitter_findings = evaluate_image_tracks(
        tracks_with_face_signal(fast_jitter),
        timestamps,
        fps=30,
        frame_width=720,
        frame_height=720,
    )
    jitter_face = jitter_metrics["face_signed_delta"]
    assert jitter_face.high_frequency_energy_ratio > 1.7
    assert jitter_face.direction_reversals_per_second > 10
    assert "image_face_signed_delta_sustained_high_frequency_exceeded" in {
        finding.code for finding in jitter_findings
    }


@pytest.mark.parametrize(
    ("amplitude", "should_fail"),
    [(0.0008, False), (0.005, True)],
)
def test_image_geometry_frequency_gate_requires_meaningful_displacement(
    amplitude: float,
    should_fail: bool,
) -> None:
    timestamps = [index / 30 for index in range(120)]
    tracks = {name: [0.0] * 120 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 120
    tracks["centroid_x"] = [
        0.5 + (amplitude if index % 2 else -amplitude) for index in range(120)
    ]

    _, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    codes = {finding.code for finding in findings}
    assert ("image_centroid_x_high_frequency_exceeded" in codes) is should_fail


def test_geometry_reversal_epsilon_scales_with_analyzed_roi_resolution() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["outline_centroid_y"] = [
        0.5 + (0.0005 if index % 2 else -0.0005) for index in range(60)
    ]

    small_metrics, small_limits, _ = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=960, frame_height=400
    )
    large_metrics, large_limits, _ = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=3840, frame_height=2000
    )

    assert small_limits["geometry_reversal_epsilon"] == pytest.approx(0.5 / 400)
    assert large_limits["geometry_reversal_epsilon"] == pytest.approx(0.5 / 2000)
    assert small_metrics["outline_centroid_y"].direction_reversals_per_second == 0
    assert large_metrics["outline_centroid_y"].direction_reversals_per_second > 20


def test_outline_gate_rejects_strong_period_two_boundary_jitter() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["outline_centroid_y"] = [
        0.5 + (0.005 if index % 2 else -0.005) for index in range(60)
    ]

    _, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    codes = {finding.code for finding in findings}
    assert "image_outline_centroid_y_reversals_exceeded" in codes
    assert "image_outline_centroid_y_high_frequency_exceeded" in codes


def test_encoded_profiles_only_add_bounded_alpha_reconstruction_margin() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["alpha_delta"] = [0.0] + [0.03] * 59
    tracks["outline_centroid_y"] = [0.5] * 30 + [0.56] * 30

    _, source_limits, source_findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=616, frame_height=676
    )
    _, final_limits, final_findings = evaluate_image_tracks(
        tracks,
        timestamps,
        fps=30,
        frame_width=616,
        frame_height=676,
        quality_profile="final_composite",
    )
    _, background_limits, background_findings = evaluate_image_tracks(
        tracks,
        timestamps,
        fps=30,
        frame_width=616,
        frame_height=676,
        quality_profile="fixed_background",
    )

    assert source_limits["alpha_delta_p99_direct"] == 0.025
    assert background_limits["alpha_delta_p99_direct"] == 0.032
    assert final_limits["alpha_delta_p99_direct"] == 0.035
    assert source_limits["outline_centroid_step"] == 0.05
    assert background_limits["outline_centroid_step"] == 0.05
    assert final_limits["outline_centroid_step"] == 0.07
    assert "image_alpha_delta_p99_direct_exceeded" in {
        finding.code for finding in source_findings
    }
    assert "image_alpha_delta_p99_direct_exceeded" not in {
        finding.code for finding in background_findings
    }
    assert "image_alpha_delta_p99_direct_exceeded" not in {
        finding.code for finding in final_findings
    }
    assert "image_outline_centroid_y_step_exceeded" in {
        finding.code for finding in source_findings
    }
    assert "image_outline_centroid_y_step_exceeded" in {
        finding.code for finding in background_findings
    }
    assert "image_outline_centroid_y_step_exceeded" not in {
        finding.code for finding in final_findings
    }


def test_image_geometry_gate_rejects_large_single_frame_centroid_jump() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["centroid_y"][30] = 0.53

    _, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    assert "image_centroid_y_step_exceeded" in {
        finding.code for finding in findings
    }


def test_image_geometry_gate_rejects_large_single_frame_outline_jump() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["outline_centroid_y"][30] = 0.56

    _, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    assert "image_outline_centroid_y_step_exceeded" in {
        finding.code for finding in findings
    }


def test_image_geometry_gate_rejects_large_single_frame_alpha_area_jump() -> None:
    timestamps = [index / 30 for index in range(60)]
    tracks = {name: [0.0] * 60 for name in IMAGE_REQUIRED_TRACKS}
    for name in (
        "alpha_area_ratio",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
    ):
        tracks[name] = [0.5] * 60
    tracks["alpha_area_ratio"][30] = 0.55

    _, _, findings = evaluate_image_tracks(
        tracks, timestamps, fps=30, frame_width=720, frame_height=720
    )

    assert "image_alpha_area_step_exceeded" in {
        finding.code for finding in findings
    }
