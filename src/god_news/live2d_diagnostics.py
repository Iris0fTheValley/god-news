from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from typing import Final, TypeVar

from god_news.live2d_control import (
    DEFAULT_DERIVATIVE_LIMITS,
    PARAMETER_FAMILIES,
    DerivativeLimits,
    ParameterFamily,
    ParameterRange,
)

T = TypeVar("T")


def pairwise(values: Iterable[T]) -> Iterator[tuple[T, T]]:
    iterator = iter(values)
    try:
        previous = next(iterator)
    except StopIteration:
        return
    for current in iterator:
        yield previous, current
        previous = current


@dataclass(frozen=True)
class SignalMetrics:
    samples: int
    duration_seconds: float
    minimum: float
    maximum: float
    p95_absolute_step: float
    p99_absolute_step: float
    maximum_absolute_step: float
    p95_absolute_velocity: float
    maximum_absolute_velocity: float
    p95_absolute_acceleration: float
    maximum_absolute_acceleration: float
    p95_absolute_jerk: float
    maximum_absolute_jerk: float
    direction_reversals_per_second: float
    high_frequency_energy_ratio: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True)
class SignalThreshold:
    maximum_absolute_step: float
    maximum_absolute_velocity: float
    maximum_absolute_acceleration: float
    maximum_absolute_jerk: float
    maximum_direction_reversals_per_second: float
    maximum_high_frequency_energy_ratio: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class GateFinding:
    code: str
    metric: str
    observed: float
    threshold: float

    def as_dict(self) -> dict[str, str | float]:
        return asdict(self)


FAMILY_REVERSAL_LIMITS: Final[dict[ParameterFamily, float]] = {
    ParameterFamily.HEAD: 5.0,
    ParameterFamily.BODY: 4.0,
    ParameterFamily.EYE_BALL: 9.0,
    ParameterFamily.EYELID: 18.0,
    ParameterFamily.MOUTH: 18.0,
    ParameterFamily.BREATH: 3.0,
}

FAMILY_HIGH_FREQUENCY_LIMITS: Final[dict[ParameterFamily, float]] = {
    ParameterFamily.HEAD: 0.55,
    ParameterFamily.BODY: 0.5,
    ParameterFamily.EYE_BALL: 0.75,
    ParameterFamily.EYELID: 1.25,
    ParameterFamily.MOUTH: 1.1,
    ParameterFamily.BREATH: 0.4,
}


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _derivative(values: list[float], timestamps: list[float]) -> list[float]:
    value_pairs = list(pairwise(values))
    time_pairs = list(pairwise(timestamps))
    return [
        (value_pairs[index][1] - value_pairs[index][0])
        / (time_pairs[index][1] - time_pairs[index][0])
        for index in range(len(value_pairs))
        for left_time, right_time in [time_pairs[index]]
        if right_time > left_time
    ]


def compute_signal_metrics(
    values: list[float],
    timestamps: list[float],
    *,
    reversal_epsilon: float,
) -> SignalMetrics:
    if len(values) != len(timestamps) or not values:
        raise ValueError("signal values and timestamps must be non-empty and aligned")
    if any(right <= left for left, right in pairwise(timestamps)):
        raise ValueError("signal timestamps must be strictly increasing")
    steps = [right - left for left, right in pairwise(values)]
    velocities = _derivative(values, timestamps)
    velocity_timestamps = timestamps[1:]
    accelerations = _derivative(velocities, velocity_timestamps)
    acceleration_timestamps = timestamps[2:]
    jerks = _derivative(accelerations, acceleration_timestamps)
    directions = [
        math.copysign(1.0, step)
        for step in steps
        if abs(step) > reversal_epsilon
    ]
    reversal_count = sum(left != right for left, right in pairwise(directions))
    duration = max(0.0, timestamps[-1] - timestamps[0])
    first_difference_energy = sum(step * step for step in steps)
    high_frequency_energy = sum(
        (right - left) ** 2 for left, right in pairwise(steps)
    )
    return SignalMetrics(
        samples=len(values),
        duration_seconds=duration,
        minimum=min(values),
        maximum=max(values),
        p95_absolute_step=_percentile([abs(value) for value in steps], 0.95),
        p99_absolute_step=_percentile([abs(value) for value in steps], 0.99),
        maximum_absolute_step=max((abs(value) for value in steps), default=0.0),
        p95_absolute_velocity=_percentile(
            [abs(value) for value in velocities],
            0.95,
        ),
        maximum_absolute_velocity=max(
            (abs(value) for value in velocities),
            default=0.0,
        ),
        p95_absolute_acceleration=_percentile(
            [abs(value) for value in accelerations],
            0.95,
        ),
        maximum_absolute_acceleration=max(
            (abs(value) for value in accelerations),
            default=0.0,
        ),
        p95_absolute_jerk=_percentile([abs(value) for value in jerks], 0.95),
        maximum_absolute_jerk=max((abs(value) for value in jerks), default=0.0),
        direction_reversals_per_second=(
            reversal_count / duration if duration > 0 else 0.0
        ),
        high_frequency_energy_ratio=(
            high_frequency_energy / first_difference_energy
            if first_difference_energy > 1e-12
            else 0.0
        ),
    )


def threshold_for_parameter(
    parameter: str,
    parameter_range: ParameterRange,
    *,
    fps: int,
    derivative_limits: dict[ParameterFamily, DerivativeLimits] | None = None,
) -> SignalThreshold:
    if fps < 1:
        raise ValueError("fps must be positive")
    family = PARAMETER_FAMILIES[parameter]
    limits = (derivative_limits or DEFAULT_DERIVATIVE_LIMITS)[family]
    velocity, acceleration, jerk = limits.for_range(parameter_range)
    # A single output step may consume at most 1.5 frames of the configured
    # velocity allowance. The multiplier absorbs 33/34 ms timestamp alternation.
    maximum_step = velocity / fps * 1.5
    return SignalThreshold(
        maximum_absolute_step=maximum_step,
        maximum_absolute_velocity=velocity * 1.1,
        maximum_absolute_acceleration=acceleration * 1.15,
        maximum_absolute_jerk=jerk * 1.2,
        maximum_direction_reversals_per_second=FAMILY_REVERSAL_LIMITS[family],
        maximum_high_frequency_energy_ratio=FAMILY_HIGH_FREQUENCY_LIMITS[family],
    )


def evaluate_signal(
    parameter: str,
    metrics: SignalMetrics,
    threshold: SignalThreshold,
) -> list[GateFinding]:
    comparisons = {
        "maximum_absolute_step": (
            metrics.maximum_absolute_step,
            threshold.maximum_absolute_step,
        ),
        "maximum_absolute_velocity": (
            metrics.maximum_absolute_velocity,
            threshold.maximum_absolute_velocity,
        ),
        "maximum_absolute_acceleration": (
            metrics.maximum_absolute_acceleration,
            threshold.maximum_absolute_acceleration,
        ),
        "maximum_absolute_jerk": (
            metrics.maximum_absolute_jerk,
            threshold.maximum_absolute_jerk,
        ),
        "direction_reversals_per_second": (
            metrics.direction_reversals_per_second,
            threshold.maximum_direction_reversals_per_second,
        ),
        "high_frequency_energy_ratio": (
            metrics.high_frequency_energy_ratio,
            threshold.maximum_high_frequency_energy_ratio,
        ),
    }
    return [
        GateFinding(
            code=f"{parameter.casefold()}_{metric}_exceeded",
            metric=metric,
            observed=observed,
            threshold=limit,
        )
        for metric, (observed, limit) in comparisons.items()
        if observed > limit
    ]


def robust_audio_calibration(raw_envelope: list[float]) -> tuple[float, float]:
    if not raw_envelope:
        raise ValueError("audio envelope cannot be empty")
    sorted_envelope = sorted(max(0.0, value) for value in raw_envelope)
    quiet = _percentile(sorted_envelope, 0.15)
    voiced_peak = _percentile(sorted_envelope, 0.95)
    noise_floor = min(0.03, max(0.0015, quiet * 1.8))
    normalization_peak = min(0.5, max(noise_floor + 0.06, voiced_peak * 1.08))
    return noise_floor, normalization_peak


def summarize_metrics(metrics: list[SignalMetrics]) -> dict[str, float]:
    if not metrics:
        return {}
    return {
        "maximum_step": max(item.maximum_absolute_step for item in metrics),
        "maximum_velocity": max(item.maximum_absolute_velocity for item in metrics),
        "maximum_acceleration": max(
            item.maximum_absolute_acceleration for item in metrics
        ),
        "maximum_jerk": max(item.maximum_absolute_jerk for item in metrics),
        "mean_reversals_per_second": statistics.fmean(
            item.direction_reversals_per_second for item in metrics
        ),
        "mean_high_frequency_energy_ratio": statistics.fmean(
            item.high_frequency_energy_ratio for item in metrics
        ),
    }
