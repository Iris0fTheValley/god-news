from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from typing import Final, Literal, TypeVar

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
    p95_absolute_value: float
    p99_absolute_value: float
    maximum_absolute_value: float
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
    alternating_energy_ratio: float

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


def _median_three(values: list[float]) -> list[float]:
    if len(values) < 3:
        return list(values)
    middle = [
        statistics.median(values[index - 1 : index + 2])
        for index in range(1, len(values) - 1)
    ]
    return [values[0], *middle, values[-1]]


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
    high_pass = [
        values[index] - (values[index - 1] + values[index + 1]) * 0.5
        for index in range(1, len(values) - 1)
    ]
    mean = statistics.fmean(high_pass) if high_pass else 0.0
    centered = [value - mean for value in high_pass]
    centered_energy = sum(value * value for value in centered)
    alternating_projection = sum(
        value if index % 2 == 0 else -value
        for index, value in enumerate(centered)
    )
    absolute_values = [abs(value) for value in values]
    return SignalMetrics(
        samples=len(values),
        duration_seconds=duration,
        minimum=min(values),
        maximum=max(values),
        p95_absolute_value=_percentile(absolute_values, 0.95),
        p99_absolute_value=_percentile(absolute_values, 0.99),
        maximum_absolute_value=max(absolute_values),
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
        alternating_energy_ratio=(
            alternating_projection * alternating_projection
            / (len(centered) * centered_energy)
            if centered_energy > 1e-12
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


IMAGE_REQUIRED_TRACKS: Final[frozenset[str]] = frozenset(
    {
        "alpha_area_ratio",
        "alpha_delta",
        "alpha_spread_x",
        "alpha_spread_y",
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
        "perceptual_delta",
        "face_delta",
        "eye_delta",
        "face_signed_delta",
        "eye_signed_delta",
        "local_flow_x",
        "local_flow_y",
        "local_flow_magnitude",
    }
)


def evaluate_image_tracks(
    tracks: dict[str, list[float]],
    timestamps: list[float],
    *,
    fps: int,
    frame_width: int,
    frame_height: int,
    quality_profile: Literal["host_source", "final_composite"] = "host_source",
) -> tuple[dict[str, SignalMetrics], dict[str, float], list[GateFinding]]:
    """Evaluate normalized image-space motion without re-differencing deltas.

    Tracks such as ``perceptual_delta`` and ``alpha_delta`` already represent
    direct inter-frame differences.  Their p95/p99/max *values* are therefore
    gated directly.  Signed regional deltas, outline/alpha geometry, and a
    lightweight local-flow estimate catch alternating flicker and scale jitter
    that a whole-frame centroid alone can miss.
    """

    if fps < 1 or frame_width < 1 or frame_height < 1:
        raise ValueError("fps and analyzed frame dimensions must be positive")
    if quality_profile not in {"host_source", "final_composite"}:
        raise ValueError("unknown image quality profile")
    missing = IMAGE_REQUIRED_TRACKS.difference(tracks)
    if missing:
        raise ValueError(f"missing image diagnostic tracks: {sorted(missing)}")
    pixel_epsilon = 0.5 / min(frame_width, frame_height)
    geometry_tracks = {
        "centroid_x",
        "centroid_y",
        "outline_centroid_x",
        "outline_centroid_y",
        "alpha_spread_x",
        "alpha_spread_y",
    }
    metrics = {
        name: compute_signal_metrics(
            values,
            timestamps,
            reversal_epsilon=(
                0.002
                if name.endswith("signed_delta") or name.startswith("local_flow")
                else pixel_epsilon
                if name in geometry_tracks
                else 0.0001
            ),
        )
        for name, values in tracks.items()
    }
    for name in geometry_tracks:
        metrics[f"{name}_stability"] = compute_signal_metrics(
            _median_three(tracks[name]),
            timestamps,
            reversal_epsilon=pixel_epsilon,
        )
    frame_scale = 30.0 / fps
    limits = {
        "geometry_reversal_epsilon": pixel_epsilon,
        # Corrected motion measured up to 0.0221 after fixed-background H.264
        # reconstruction across the authoritative model motion set. 0.025 keeps
        # codec/float margin while the 0.03 teleport regression and independent
        # parameter, regional-delta, flow, reversal, and period-two gates remain.
        "centroid_step": 0.025 * frame_scale,
        "centroid_reversals_per_second": 10.0,
        "centroid_high_frequency_ratio": 0.9,
        "centroid_high_frequency_min_reversals": 8.0,
        "centroid_high_frequency_min_p95_step": 0.0027 * frame_scale,
        # The VP9 decoder exposed by PyAV omits alpha and requires a bounded
        # color-distance reconstruction. Corrected A/B renders measured up to
        # 0.0377 at 512px and 0.0457 at 720px while subject centroid stayed
        # below 0.018 and alternating energy stayed near zero. 0.050 retains
        # codec/segmentation margin while centroid, regional delta, flow,
        # reversal, and period-two gates still reject visual jitter.
        "outline_centroid_step": 0.050 * frame_scale,
        "outline_reversals_per_second": 12.0,
        "outline_high_frequency_ratio": 1.1,
        "outline_high_frequency_min_reversals": 8.0,
        "outline_high_frequency_min_p95_step": 0.0052 * frame_scale,
        # Smooth arm motion can change silhouette self-overlap by ~0.022
        # pre-encode and ~0.028 after fixed-background segmentation in one
        # frame. Preserve a hard teleport bound while period-two and direct
        # alpha-delta gates detect sustained flicker independently.
        "alpha_area_step": 0.040 * frame_scale,
        "alpha_spread_step": 0.018 * frame_scale,
        "alpha_delta_p99_direct": 0.025,
        "alpha_delta_max_direct": 0.050,
        "perceptual_delta_p99_direct": 0.160,
        "perceptual_delta_max_direct": 0.280,
        "face_delta_p99_direct": 0.180,
        "face_delta_max_direct": 0.320,
        "eye_delta_p99_direct": 0.280,
        "eye_delta_max_direct": 0.450,
        "local_flow_p99_direct": 0.120,
        "local_flow_max_direct": 0.250,
        "signed_delta_amplitude_floor": 0.012,
        "signed_delta_reversals_per_second": 18.0,
        "signed_delta_high_frequency_ratio": 1.7,
        "signed_delta_high_frequency_min_reversals": 10.0,
        "signed_delta_alternating_energy_ratio": 0.45,
        "geometry_alternating_energy_ratio": 0.45,
    }
    if quality_profile == "final_composite":
        # The final profile is measured after host scaling plus a second lossy
        # H.264 encode. Regional RGB/flow gates remain unchanged; only alpha
        # reconstructed from the opaque composition receives codec margin.
        limits["alpha_delta_p99_direct"] = 0.035
        limits["alpha_delta_max_direct"] = 0.060
    checks: dict[str, tuple[float, float]] = {
        "centroid_x_step": (
            metrics["centroid_x"].maximum_absolute_step,
            limits["centroid_step"],
        ),
        "centroid_y_step": (
            metrics["centroid_y"].maximum_absolute_step,
            limits["centroid_step"],
        ),
        "centroid_x_reversals": (
            metrics["centroid_x_stability"].direction_reversals_per_second,
            limits["centroid_reversals_per_second"],
        ),
        "centroid_y_reversals": (
            metrics["centroid_y_stability"].direction_reversals_per_second,
            limits["centroid_reversals_per_second"],
        ),
        "outline_centroid_x_step": (
            metrics["outline_centroid_x"].maximum_absolute_step,
            limits["outline_centroid_step"],
        ),
        "outline_centroid_y_step": (
            metrics["outline_centroid_y"].maximum_absolute_step,
            limits["outline_centroid_step"],
        ),
        "alpha_area_step": (
            metrics["alpha_area_ratio"].maximum_absolute_step,
            limits["alpha_area_step"],
        ),
        "alpha_spread_x_step": (
            metrics["alpha_spread_x"].maximum_absolute_step,
            limits["alpha_spread_step"],
        ),
        "alpha_spread_y_step": (
            metrics["alpha_spread_y"].maximum_absolute_step,
            limits["alpha_spread_step"],
        ),
        "alpha_delta_p99_direct": (
            metrics["alpha_delta"].p99_absolute_value,
            limits["alpha_delta_p99_direct"],
        ),
        "alpha_delta_max_direct": (
            metrics["alpha_delta"].maximum_absolute_value,
            limits["alpha_delta_max_direct"],
        ),
        "perceptual_delta_p99_direct": (
            metrics["perceptual_delta"].p99_absolute_value,
            limits["perceptual_delta_p99_direct"],
        ),
        "perceptual_delta_max_direct": (
            metrics["perceptual_delta"].maximum_absolute_value,
            limits["perceptual_delta_max_direct"],
        ),
        "face_delta_p99_direct": (
            metrics["face_delta"].p99_absolute_value,
            limits["face_delta_p99_direct"],
        ),
        "face_delta_max_direct": (
            metrics["face_delta"].maximum_absolute_value,
            limits["face_delta_max_direct"],
        ),
        "eye_delta_p99_direct": (
            metrics["eye_delta"].p99_absolute_value,
            limits["eye_delta_p99_direct"],
        ),
        "eye_delta_max_direct": (
            metrics["eye_delta"].maximum_absolute_value,
            limits["eye_delta_max_direct"],
        ),
        "local_flow_p99_direct": (
            metrics["local_flow_magnitude"].p99_absolute_value,
            limits["local_flow_p99_direct"],
        ),
        "local_flow_max_direct": (
            metrics["local_flow_magnitude"].maximum_absolute_value,
            limits["local_flow_max_direct"],
        ),
    }
    findings = [
        GateFinding(
            code=f"image_{name}_exceeded",
            metric=name,
            observed=observed,
            threshold=threshold,
        )
        for name, (observed, threshold) in checks.items()
        if observed > threshold
    ]
    # A single normal scene entrance can have high second-difference energy.
    # Treat it as high-frequency jitter only when it is also reversing often;
    # sustained alternating motion therefore fails while one bounded transient
    # does not.
    for name, frequency_limit, reversal_floor, step_floor, alternating_floor in (
        (
            "centroid_x",
            limits["centroid_high_frequency_ratio"],
            limits["centroid_high_frequency_min_reversals"],
            limits["centroid_high_frequency_min_p95_step"],
            0.0,
        ),
        (
            "centroid_y",
            limits["centroid_high_frequency_ratio"],
            limits["centroid_high_frequency_min_reversals"],
            limits["centroid_high_frequency_min_p95_step"],
            0.0,
        ),
        (
            "outline_centroid_x",
            limits["outline_high_frequency_ratio"],
            limits["outline_high_frequency_min_reversals"],
            limits["outline_high_frequency_min_p95_step"],
            limits["geometry_alternating_energy_ratio"],
        ),
        (
            "outline_centroid_y",
            limits["outline_high_frequency_ratio"],
            limits["outline_high_frequency_min_reversals"],
            limits["outline_high_frequency_min_p95_step"],
            limits["geometry_alternating_energy_ratio"],
        ),
    ):
        item = metrics[f"{name}_stability"]
        if (
            item.high_frequency_energy_ratio > frequency_limit
            and item.direction_reversals_per_second > reversal_floor
            and item.p95_absolute_step > step_floor
            and item.alternating_energy_ratio > alternating_floor
        ):
            findings.append(
                GateFinding(
                    code=f"image_{name}_high_frequency_exceeded",
                    metric=f"{name}_high_frequency",
                    observed=item.high_frequency_energy_ratio,
                    threshold=frequency_limit,
                )
            )
    for name in ("outline_centroid_x", "outline_centroid_y"):
        item = metrics[f"{name}_stability"]
        if (
            item.direction_reversals_per_second
            > limits["outline_reversals_per_second"]
            and item.p95_absolute_step
            > limits["outline_high_frequency_min_p95_step"]
            and item.alternating_energy_ratio
            > limits["geometry_alternating_energy_ratio"]
        ):
            findings.append(
                GateFinding(
                    code=f"image_{name}_reversals_exceeded",
                    metric=f"{name}_reversals",
                    observed=item.direction_reversals_per_second,
                    threshold=limits["outline_reversals_per_second"],
                )
            )
    amplitude_floor = limits["signed_delta_amplitude_floor"]
    for name in ("face_signed_delta", "eye_signed_delta"):
        item = metrics[name]
        if item.p95_absolute_value <= amplitude_floor:
            continue
        conditional_checks = {
            f"{name}_reversals": (
                item.direction_reversals_per_second,
                limits["signed_delta_reversals_per_second"],
            ),
            f"{name}_period_two": (
                item.alternating_energy_ratio,
                limits["signed_delta_alternating_energy_ratio"],
            ),
        }
        findings.extend(
            GateFinding(
                code=f"image_{metric_name}_exceeded",
                metric=metric_name,
                observed=observed,
                threshold=threshold,
            )
            for metric_name, (observed, threshold) in conditional_checks.items()
            if observed > threshold
        )
        if (
            item.high_frequency_energy_ratio
            > limits["signed_delta_high_frequency_ratio"]
            and item.direction_reversals_per_second
            > limits["signed_delta_high_frequency_min_reversals"]
        ):
            findings.append(
                GateFinding(
                    code=f"image_{name}_high_frequency_exceeded",
                    metric=f"{name}_high_frequency",
                    observed=item.high_frequency_energy_ratio,
                    threshold=limits["signed_delta_high_frequency_ratio"],
                )
            )
    for name in ("alpha_area_ratio", "alpha_spread_x", "alpha_spread_y"):
        item = metrics[name]
        if (
            item.p95_absolute_step > 0.002
            and item.alternating_energy_ratio
            > limits["geometry_alternating_energy_ratio"]
        ):
            findings.append(
                GateFinding(
                    code=f"image_{name}_period_two_exceeded",
                    metric=f"{name}_period_two",
                    observed=item.alternating_energy_ratio,
                    threshold=limits["geometry_alternating_energy_ratio"],
                )
            )
    return metrics, limits, findings


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
