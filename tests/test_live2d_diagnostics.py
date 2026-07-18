from __future__ import annotations

import math

import pytest

from god_news.live2d_control import PARAM_ANGLE_X, ParameterRange
from god_news.live2d_diagnostics import (
    compute_signal_metrics,
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
