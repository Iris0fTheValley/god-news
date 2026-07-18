from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, cast

PARAM_ANGLE_X: Final = "PARAM_ANGLE_X"
PARAM_ANGLE_Y: Final = "PARAM_ANGLE_Y"
PARAM_ANGLE_Z: Final = "PARAM_ANGLE_Z"
PARAM_BODY_ANGLE_X: Final = "PARAM_BODY_ANGLE_X"
PARAM_EYE_BALL_X: Final = "PARAM_EYE_BALL_X"
PARAM_EYE_BALL_Y: Final = "PARAM_EYE_BALL_Y"
PARAM_EYE_L_OPEN: Final = "PARAM_EYE_L_OPEN"
PARAM_EYE_R_OPEN: Final = "PARAM_EYE_R_OPEN"
PARAM_MOUTH_OPEN_Y: Final = "PARAM_MOUTH_OPEN_Y"
PARAM_BREATH: Final = "PARAM_BREATH"

CONTROLLED_PARAMETERS: Final = (
    PARAM_ANGLE_X,
    PARAM_ANGLE_Y,
    PARAM_ANGLE_Z,
    PARAM_BODY_ANGLE_X,
    PARAM_EYE_BALL_X,
    PARAM_EYE_BALL_Y,
    PARAM_EYE_L_OPEN,
    PARAM_EYE_R_OPEN,
    PARAM_MOUTH_OPEN_Y,
    PARAM_BREATH,
)


class Live2DControlMode(str, Enum):  # noqa: UP042 - worker runtime is Python 3.9
    LEGACY_CONFLICT = "legacy_conflict"
    MOTION_ONLY = "motion_only"
    PROCEDURAL_ONLY = "procedural_only"
    NO_LIP_SYNC = "no_lip_sync"
    FINAL = "final"


class ParameterFamily(str, Enum):  # noqa: UP042 - worker runtime is Python 3.9
    HEAD = "head"
    BODY = "body"
    EYE_BALL = "eye_ball"
    EYELID = "eyelid"
    MOUTH = "mouth"
    BREATH = "breath"


class ParameterOwner(str, Enum):  # noqa: UP042 - worker runtime is Python 3.9
    CONFLICTING_WRITERS = "conflicting_writers"
    MOTION_SAMPLER = "motion_sampler"
    PROCEDURAL_POSE_MIXER = "procedural_pose_mixer"
    NEUTRAL_MOUTH_CONTROLLER = "neutral_mouth_controller"
    MOTION_MIXER = "motion_mixer"
    EYE_GAZE_MIXER = "eye_gaze_mixer"
    BLINK_CONTROLLER = "blink_controller"
    LIP_SYNC_CONTROLLER = "lip_sync_controller"
    BREATH_CONTROLLER = "breath_controller"


PARAMETER_FAMILIES: Final[dict[str, ParameterFamily]] = {
    PARAM_ANGLE_X: ParameterFamily.HEAD,
    PARAM_ANGLE_Y: ParameterFamily.HEAD,
    PARAM_ANGLE_Z: ParameterFamily.HEAD,
    PARAM_BODY_ANGLE_X: ParameterFamily.BODY,
    PARAM_EYE_BALL_X: ParameterFamily.EYE_BALL,
    PARAM_EYE_BALL_Y: ParameterFamily.EYE_BALL,
    PARAM_EYE_L_OPEN: ParameterFamily.EYELID,
    PARAM_EYE_R_OPEN: ParameterFamily.EYELID,
    PARAM_MOUTH_OPEN_Y: ParameterFamily.MOUTH,
    PARAM_BREATH: ParameterFamily.BREATH,
}

PARAMETER_OWNERS: Final[dict[str, ParameterOwner]] = {
    PARAM_ANGLE_X: ParameterOwner.MOTION_MIXER,
    PARAM_ANGLE_Y: ParameterOwner.MOTION_MIXER,
    PARAM_ANGLE_Z: ParameterOwner.MOTION_MIXER,
    PARAM_BODY_ANGLE_X: ParameterOwner.MOTION_MIXER,
    PARAM_EYE_BALL_X: ParameterOwner.EYE_GAZE_MIXER,
    PARAM_EYE_BALL_Y: ParameterOwner.EYE_GAZE_MIXER,
    PARAM_EYE_L_OPEN: ParameterOwner.BLINK_CONTROLLER,
    PARAM_EYE_R_OPEN: ParameterOwner.BLINK_CONTROLLER,
    PARAM_MOUTH_OPEN_Y: ParameterOwner.LIP_SYNC_CONTROLLER,
    PARAM_BREATH: ParameterOwner.BREATH_CONTROLLER,
}


def effective_parameter_owner(
    mode: Live2DControlMode,
    parameter: str,
) -> ParameterOwner:
    if mode is Live2DControlMode.LEGACY_CONFLICT:
        return ParameterOwner.CONFLICTING_WRITERS
    if mode is Live2DControlMode.MOTION_ONLY and parameter != PARAM_MOUTH_OPEN_Y:
        return ParameterOwner.MOTION_SAMPLER
    if (
        mode is Live2DControlMode.PROCEDURAL_ONLY
        and parameter
        in {
            PARAM_ANGLE_X,
            PARAM_ANGLE_Y,
            PARAM_ANGLE_Z,
            PARAM_BODY_ANGLE_X,
        }
    ):
        return ParameterOwner.PROCEDURAL_POSE_MIXER
    if mode is Live2DControlMode.NO_LIP_SYNC and parameter == PARAM_MOUTH_OPEN_Y:
        return ParameterOwner.NEUTRAL_MOUTH_CONTROLLER
    return PARAMETER_OWNERS[parameter]


@dataclass(frozen=True)
class ParameterRange:
    minimum: float
    maximum: float
    default: float

    @property
    def span(self) -> float:
        return self.maximum - self.minimum

    def clamp(self, value: float) -> float:
        return min(self.maximum, max(self.minimum, value))


@dataclass(frozen=True)
class DerivativeLimits:
    """Kinematic limits expressed as fractions of the model range per second."""

    velocity_spans_per_second: float
    acceleration_spans_per_second2: float
    jerk_spans_per_second3: float

    def for_range(self, parameter_range: ParameterRange) -> tuple[float, float, float]:
        span = max(parameter_range.span, 1e-9)
        return (
            span * self.velocity_spans_per_second,
            span * self.acceleration_spans_per_second2,
            span * self.jerk_spans_per_second3,
        )


# These are safety rails, not acceptance thresholds. They are normalized by the
# actual Cubism parameter range and are calibrated again from the A/B traces.
DEFAULT_DERIVATIVE_LIMITS: Final[dict[ParameterFamily, DerivativeLimits]] = {
    ParameterFamily.HEAD: DerivativeLimits(0.9, 4.0, 30.0),
    ParameterFamily.BODY: DerivativeLimits(0.75, 3.5, 24.0),
    ParameterFamily.EYE_BALL: DerivativeLimits(1.6, 10.0, 90.0),
    # A smooth 85 ms close / 130 ms open blink needs much higher derivatives
    # than head motion. These limits follow the analytical smoothstep maxima
    # with a small model-range margin; legacy frame-flash traces still exceed
    # the resulting jerk and reversal gates.
    ParameterFamily.EYELID: DerivativeLimits(14.0, 650.0, 15_000.0),
    ParameterFamily.MOUTH: DerivativeLimits(7.0, 80.0, 900.0),
    ParameterFamily.BREATH: DerivativeLimits(0.8, 3.0, 18.0),
}


def _move_towards(current: float, target: float, maximum_delta: float) -> float:
    delta = target - current
    if abs(delta) <= maximum_delta:
        return target
    return current + math.copysign(maximum_delta, delta)


@dataclass
class KinematicLimiter:
    value: float
    velocity: float = 0.0
    acceleration: float = 0.0

    def update(
        self,
        target: float,
        *,
        delta_seconds: float,
        maximum_velocity: float,
        maximum_acceleration: float,
        maximum_jerk: float,
    ) -> float:
        if delta_seconds <= 0:
            return self.value
        distance = target - self.value
        natural_frequency = max(
            0.1,
            maximum_acceleration / max(maximum_velocity, 1e-9),
        )
        desired_acceleration = (
            natural_frequency * natural_frequency * distance
            - 2 * natural_frequency * self.velocity
        )
        desired_acceleration = max(
            -maximum_acceleration,
            min(maximum_acceleration, desired_acceleration),
        )
        if desired_acceleration > 0:
            velocity_headroom = max(0.0, maximum_velocity - self.velocity)
            desired_acceleration = min(
                desired_acceleration,
                math.sqrt(2 * maximum_jerk * velocity_headroom),
            )
        elif desired_acceleration < 0:
            velocity_headroom = max(0.0, maximum_velocity + self.velocity)
            desired_acceleration = max(
                desired_acceleration,
                -math.sqrt(2 * maximum_jerk * velocity_headroom),
            )
        acceleration_delta = maximum_jerk * delta_seconds
        next_acceleration = _move_towards(
            self.acceleration,
            desired_acceleration,
            acceleration_delta,
        )
        next_velocity = self.velocity + next_acceleration * delta_seconds
        next_velocity = max(-maximum_velocity, min(maximum_velocity, next_velocity))
        next_value = self.value + next_velocity * delta_seconds
        if (
            abs(target - next_value) < 1e-5
            and abs(next_velocity) < 1e-4
            and abs(next_acceleration) < 1e-3
        ):
            next_value = target
            next_velocity = 0.0
            next_acceleration = 0.0
        self.value = next_value
        self.velocity = next_velocity
        self.acceleration = next_acceleration
        return self.value


@dataclass(frozen=True)
class SpringSettings:
    frequency_hz: float
    damping_ratio: float = 1.0
    maximum_velocity: float = math.inf
    maximum_acceleration: float = math.inf


@dataclass
class SpringDamper:
    value: float
    velocity: float = 0.0

    def update(
        self,
        target: float,
        *,
        delta_seconds: float,
        settings: SpringSettings,
    ) -> float:
        if delta_seconds <= 0:
            return self.value
        # Substeps keep semi-implicit Euler stable under irregular render deltas.
        remaining = min(delta_seconds, 0.25)
        while remaining > 1e-9:
            step = min(remaining, 1 / 120)
            omega = 2 * math.pi * settings.frequency_hz
            acceleration = (
                omega * omega * (target - self.value)
                - 2 * settings.damping_ratio * omega * self.velocity
            )
            acceleration = max(
                -settings.maximum_acceleration,
                min(settings.maximum_acceleration, acceleration),
            )
            self.velocity += acceleration * step
            self.velocity = max(
                -settings.maximum_velocity,
                min(settings.maximum_velocity, self.velocity),
            )
            self.value += self.velocity * step
            remaining -= step
        if abs(target - self.value) < 1e-6 and abs(self.velocity) < 1e-5:
            self.value = target
            self.velocity = 0.0
        return self.value


class BlinkState(str, Enum):  # noqa: UP042 - worker runtime is Python 3.9
    WAITING = "waiting"
    CLOSING = "closing"
    CLOSED = "closed"
    OPENING = "opening"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class BlinkSettings:
    minimum_interval_seconds: float = 2.8
    maximum_interval_seconds: float = 5.2
    close_seconds: float = 0.085
    closed_seconds: float = 0.045
    open_seconds: float = 0.13
    recovery_seconds: float = 0.11


@dataclass
class BlinkController:
    settings: BlinkSettings = field(default_factory=BlinkSettings)
    seed: int = 42
    state: BlinkState = BlinkState.WAITING
    openness: float = 1.0
    _elapsed: float = 0.0
    _waiting_for: float = 0.0
    _random: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)
        self._schedule_next()

    def _schedule_next(self) -> None:
        self._waiting_for = self._random.uniform(
            self.settings.minimum_interval_seconds,
            self.settings.maximum_interval_seconds,
        )
        self._elapsed = 0.0

    @staticmethod
    def _smoothstep(value: float) -> float:
        value = min(1.0, max(0.0, value))
        return value * value * (3 - 2 * value)

    def update(self, delta_seconds: float, *, enabled: bool = True) -> float:
        if delta_seconds <= 0:
            return self.openness
        if not enabled:
            if self.state is not BlinkState.WAITING or self.openness != 1.0:
                self.state = BlinkState.WAITING
                self.openness = 1.0
                self._schedule_next()
            self._elapsed = 0.0
            return self.openness
        self._elapsed += delta_seconds
        if self.state is BlinkState.WAITING:
            self.openness = 1.0
            if self._elapsed >= self._waiting_for:
                self.state = BlinkState.CLOSING
                self._elapsed = 0.0
        elif self.state is BlinkState.CLOSING:
            progress = self._elapsed / self.settings.close_seconds
            self.openness = 1.0 - self._smoothstep(progress)
            if progress >= 1:
                self.state = BlinkState.CLOSED
                self._elapsed = 0.0
                self.openness = 0.0
        elif self.state is BlinkState.CLOSED:
            self.openness = 0.0
            if self._elapsed >= self.settings.closed_seconds:
                self.state = BlinkState.OPENING
                self._elapsed = 0.0
        elif self.state is BlinkState.OPENING:
            progress = self._elapsed / self.settings.open_seconds
            self.openness = self._smoothstep(progress)
            if progress >= 1:
                self.state = BlinkState.RECOVERY
                self._elapsed = 0.0
                self.openness = 1.0
        else:
            self.openness = 1.0
            if self._elapsed >= self.settings.recovery_seconds:
                self.state = BlinkState.WAITING
                self._schedule_next()
        return self.openness


@dataclass(frozen=True)
class MouthSettings:
    noise_floor: float
    normalization_peak: float
    open_threshold: float = 0.055
    close_threshold: float = 0.028
    minimum_hold_seconds: float = 0.075
    dead_zone: float = 0.018
    attack_seconds: float = 0.055
    release_seconds: float = 0.16
    power: float = 0.76
    maximum_velocity: float = 7.0
    maximum_acceleration: float = 80.0
    maximum_jerk: float = 900.0


@dataclass(frozen=True)
class MouthFrame:
    raw_envelope: float
    normalized_envelope: float
    gated_envelope: float
    smoothed_target: float
    final_value: float
    gate_open: bool


@dataclass
class MouthController:
    settings: MouthSettings
    gate_open: bool = False
    _hold_remaining: float = 0.0
    _smoothed_target: float = 0.0
    _limiter: KinematicLimiter = field(default_factory=lambda: KinematicLimiter(0.0))

    def _normalize(self, raw_envelope: float) -> float:
        span = max(1e-6, self.settings.normalization_peak - self.settings.noise_floor)
        normalized = (raw_envelope - self.settings.noise_floor) / span
        return cast(float, min(1.0, max(0.0, normalized)) ** self.settings.power)

    def update(self, raw_envelope: float, *, delta_seconds: float) -> MouthFrame:
        normalized = self._normalize(raw_envelope)
        if self.gate_open:
            self._hold_remaining = max(0.0, self._hold_remaining - delta_seconds)
            if (
                normalized <= self.settings.close_threshold
                and self._hold_remaining <= 0
            ):
                self.gate_open = False
        elif normalized >= self.settings.open_threshold:
            self.gate_open = True
            self._hold_remaining = self.settings.minimum_hold_seconds

        gated = normalized if self.gate_open else 0.0
        if gated < self.settings.dead_zone:
            gated = 0.0
        time_constant = (
            self.settings.attack_seconds
            if gated > self._smoothed_target
            else self.settings.release_seconds
        )
        coefficient = 1.0 - math.exp(-delta_seconds / max(time_constant, 1e-6))
        self._smoothed_target += (gated - self._smoothed_target) * coefficient
        final_value = self._limiter.update(
            self._smoothed_target,
            delta_seconds=delta_seconds,
            maximum_velocity=self.settings.maximum_velocity,
            maximum_acceleration=self.settings.maximum_acceleration,
            maximum_jerk=self.settings.maximum_jerk,
        )
        if not self.gate_open and final_value < self.settings.dead_zone / 2:
            final_value = 0.0
            self._limiter.value = 0.0
            self._limiter.velocity = 0.0
            self._limiter.acceleration = 0.0
        return MouthFrame(
            raw_envelope=raw_envelope,
            normalized_envelope=normalized,
            gated_envelope=gated,
            smoothed_target=self._smoothed_target,
            final_value=min(1.0, max(0.0, final_value)),
            gate_open=self.gate_open,
        )


class MotionState(str, Enum):  # noqa: UP042 - worker runtime is Python 3.9
    IDLE = "idle"
    ENTERING = "entering_motion"
    PLAYING = "playing_motion"
    EXITING = "exiting_motion"
    RETURNING_TO_NEUTRAL = "returning_to_neutral"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class MotionTransitionSettings:
    fade_in_seconds: float = 0.8
    fade_out_seconds: float = 0.8
    return_seconds: float = 0.35
    cooldown_seconds: float = 0.45
    minimum_motion_interval_seconds: float = 1.0


@dataclass(frozen=True)
class MotionTransitionFrame:
    state: MotionState
    blend_weight: float
    start_motion: bool
    completed_transition: bool


@dataclass
class MotionTransitionController:
    settings: MotionTransitionSettings = field(default_factory=MotionTransitionSettings)
    state: MotionState = MotionState.IDLE
    blend_weight: float = 0.0
    _elapsed: float = 0.0
    _time_since_start: float = math.inf

    @staticmethod
    def _smoothstep(value: float) -> float:
        value = min(1.0, max(0.0, value))
        return value * value * (3 - 2 * value)

    def update(
        self,
        *,
        delta_seconds: float,
        motion_finished: bool,
        motion_available: bool,
    ) -> MotionTransitionFrame:
        self._elapsed += max(0.0, delta_seconds)
        self._time_since_start += max(0.0, delta_seconds)
        start_motion = False
        completed_transition = False
        if self.state is MotionState.IDLE:
            self.blend_weight = 0.0
            if motion_available:
                self.state = MotionState.ENTERING
                self._elapsed = 0.0
                self._time_since_start = 0.0
                start_motion = True
        elif self.state is MotionState.ENTERING:
            progress = self._elapsed / self.settings.fade_in_seconds
            self.blend_weight = self._smoothstep(progress)
            if progress >= 1:
                self.state = MotionState.PLAYING
                self._elapsed = 0.0
                self.blend_weight = 1.0
        elif self.state is MotionState.PLAYING:
            self.blend_weight = 1.0
            if (
                motion_finished
                and self._time_since_start >= self.settings.minimum_motion_interval_seconds
            ):
                self.state = MotionState.EXITING
                self._elapsed = 0.0
        elif self.state is MotionState.EXITING:
            progress = self._elapsed / self.settings.fade_out_seconds
            self.blend_weight = 1.0 - self._smoothstep(progress)
            if progress >= 1:
                self.state = MotionState.RETURNING_TO_NEUTRAL
                self._elapsed = 0.0
                self.blend_weight = 0.0
        elif self.state is MotionState.RETURNING_TO_NEUTRAL:
            self.blend_weight = 0.0
            if self._elapsed >= self.settings.return_seconds:
                self.state = MotionState.COOLDOWN
                self._elapsed = 0.0
                completed_transition = True
        else:
            self.blend_weight = 0.0
            if self._elapsed >= self.settings.cooldown_seconds:
                self.state = MotionState.IDLE
                self._elapsed = 0.0
        return MotionTransitionFrame(
            state=self.state,
            blend_weight=self.blend_weight,
            start_motion=start_motion,
            completed_transition=completed_transition,
        )


@dataclass(frozen=True)
class ProceduralPose:
    idle: dict[str, float]
    look: dict[str, float]
    breath: float


@dataclass
class ProceduralPoseController:
    seed: int = 42
    _random: random.Random = field(init=False, repr=False)
    _elapsed: float = 0.0
    _target_hold: float = 0.0
    _idle_targets: dict[str, float] = field(default_factory=dict)
    _look_targets: dict[str, float] = field(default_factory=dict)
    _springs: dict[str, SpringDamper] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._random = random.Random(self.seed)
        for parameter in (
            PARAM_ANGLE_X,
            PARAM_ANGLE_Y,
            PARAM_ANGLE_Z,
            PARAM_BODY_ANGLE_X,
            PARAM_EYE_BALL_X,
            PARAM_EYE_BALL_Y,
        ):
            self._springs[parameter] = SpringDamper(0.0)
        self._choose_targets()

    def _choose_targets(self) -> None:
        self._target_hold = self._random.uniform(2.4, 4.8)
        self._elapsed = 0.0
        self._idle_targets = {
            PARAM_ANGLE_X: self._random.uniform(-1.5, 1.5),
            PARAM_ANGLE_Y: self._random.uniform(-1.0, 1.0),
            PARAM_ANGLE_Z: self._random.uniform(-0.65, 0.65),
            PARAM_BODY_ANGLE_X: self._random.uniform(-0.5, 0.5),
        }
        self._look_targets = {
            PARAM_EYE_BALL_X: self._random.uniform(-0.24, 0.24),
            PARAM_EYE_BALL_Y: self._random.uniform(-0.14, 0.12),
        }

    def update(
        self,
        *,
        timestamp_seconds: float,
        delta_seconds: float,
        motion_weight: float,
    ) -> ProceduralPose:
        self._elapsed += max(0.0, delta_seconds)
        if self._elapsed >= self._target_hold:
            self._choose_targets()
        idle_weight = max(0.08, 1.0 - 0.92 * motion_weight)
        idle: dict[str, float] = {}
        for parameter, target in self._idle_targets.items():
            idle[parameter] = self._springs[parameter].update(
                target * idle_weight,
                delta_seconds=delta_seconds,
                settings=SpringSettings(
                    frequency_hz=0.42,
                    damping_ratio=1.1,
                    maximum_velocity=2.0,
                    maximum_acceleration=7.0,
                ),
            )
        look_weight = max(0.2, 1.0 - 0.8 * motion_weight)
        look: dict[str, float] = {}
        for parameter, target in self._look_targets.items():
            look[parameter] = self._springs[parameter].update(
                target * look_weight,
                delta_seconds=delta_seconds,
                settings=SpringSettings(
                    frequency_hz=0.62,
                    damping_ratio=1.0,
                    maximum_velocity=0.55,
                    maximum_acceleration=2.4,
                ),
            )
        breath = 0.5 + 0.08 * math.sin(timestamp_seconds * math.tau / 4.8)
        return ProceduralPose(idle=idle, look=look, breath=breath)


@dataclass(frozen=True)
class ParameterContribution:
    base: float
    motion: float | None
    expression: float | None
    idle: float | None
    look: float | None
    breath: float | None
    blink: float | None
    lip_sync: float | None
    desired: float
    final: float
    owner: ParameterOwner


@dataclass
class ParameterMixer:
    parameter_ranges: dict[str, ParameterRange]
    derivative_limits: dict[ParameterFamily, DerivativeLimits] = field(
        default_factory=lambda: dict(DEFAULT_DERIVATIVE_LIMITS)
    )
    _limiters: dict[str, KinematicLimiter] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._limiters = {
            parameter: KinematicLimiter(parameter_range.default)
            for parameter, parameter_range in self.parameter_ranges.items()
        }

    def mix(
        self,
        *,
        delta_seconds: float,
        mode: Live2DControlMode,
        base_values: dict[str, float],
        motion_values: dict[str, float],
        motion_weight: float,
        procedural_pose: ProceduralPose,
        blink_openness: float,
        blink_owned: bool,
        mouth_value: float,
    ) -> dict[str, ParameterContribution]:
        contributions: dict[str, ParameterContribution] = {}
        motion_enabled = mode in {
            Live2DControlMode.MOTION_ONLY,
            Live2DControlMode.NO_LIP_SYNC,
            Live2DControlMode.FINAL,
        }
        procedural_enabled = mode in {
            Live2DControlMode.PROCEDURAL_ONLY,
            Live2DControlMode.NO_LIP_SYNC,
            Live2DControlMode.FINAL,
        }
        lip_sync_enabled = mode is not Live2DControlMode.NO_LIP_SYNC
        for parameter, parameter_range in self.parameter_ranges.items():
            base = base_values.get(parameter, parameter_range.default)
            motion = motion_values.get(parameter) if motion_enabled else None
            idle = procedural_pose.idle.get(parameter) if procedural_enabled else None
            look = procedural_pose.look.get(parameter) if procedural_enabled else None
            breath = (
                procedural_pose.breath
                if procedural_enabled and parameter == PARAM_BREATH
                else None
            )
            blink = (
                blink_openness
                if procedural_enabled
                and parameter in {PARAM_EYE_L_OPEN, PARAM_EYE_R_OPEN}
                else None
            )
            lip_sync = (
                mouth_value
                if lip_sync_enabled and parameter == PARAM_MOUTH_OPEN_Y
                else None
            )
            expression: float | None = None
            if parameter in {
                PARAM_ANGLE_X,
                PARAM_ANGLE_Y,
                PARAM_ANGLE_Z,
                PARAM_BODY_ANGLE_X,
            }:
                desired = (
                    base + (motion - base) * motion_weight
                    if motion is not None
                    else base
                )
                if idle is not None:
                    desired += idle
            elif parameter in {PARAM_EYE_BALL_X, PARAM_EYE_BALL_Y}:
                motion_base = (
                    base + (motion - base) * motion_weight
                    if motion is not None
                    else base
                )
                desired = look if look is not None else motion_base
                if look is not None and motion is not None:
                    desired = motion_base * motion_weight + look * (1 - motion_weight)
            elif parameter in {PARAM_EYE_L_OPEN, PARAM_EYE_R_OPEN}:
                if mode is Live2DControlMode.MOTION_ONLY:
                    desired = (
                        base + (motion - base) * motion_weight
                        if motion is not None
                        else base
                    )
                else:
                    # Eyelids have exactly one production owner. Emotion
                    # motions may animate the face, but cannot also overwrite
                    # the procedural blink curve.
                    desired = blink if blink is not None else base
            elif parameter == PARAM_MOUTH_OPEN_Y:
                if lip_sync is not None:
                    desired = lip_sync
                elif mode is Live2DControlMode.MOTION_ONLY:
                    desired = (
                        base + (motion - base) * motion_weight
                        if motion is not None
                        else base
                    )
                else:
                    desired = base
            elif parameter == PARAM_BREATH:
                if mode is Live2DControlMode.MOTION_ONLY:
                    desired = (
                    base + (motion - base) * motion_weight
                        if motion is not None
                        else base
                    )
                else:
                    # The breath oscillator owns this parameter in production;
                    # motion files are not allowed to compete for it.
                    desired = breath if breath is not None else base
            else:
                desired = base
            desired = parameter_range.clamp(desired)
            family = PARAMETER_FAMILIES[parameter]
            velocity, acceleration, jerk = self.derivative_limits[family].for_range(
                parameter_range
            )
            limiter = self._limiters[parameter]
            if family is ParameterFamily.EYELID and blink_owned:
                previous_value = limiter.value
                previous_velocity = limiter.velocity
                final = desired
                limiter.value = final
                limiter.velocity = (
                    (final - previous_value) / delta_seconds
                    if delta_seconds > 0
                    else 0.0
                )
                limiter.acceleration = (
                    (limiter.velocity - previous_velocity) / delta_seconds
                    if delta_seconds > 0
                    else 0.0
                )
            else:
                final = limiter.update(
                    desired,
                    delta_seconds=delta_seconds,
                    maximum_velocity=velocity,
                    maximum_acceleration=acceleration,
                    maximum_jerk=jerk,
                )
            final = parameter_range.clamp(final)
            limiter.value = final
            contributions[parameter] = ParameterContribution(
                base=base,
                motion=motion,
                expression=expression,
                idle=idle,
                look=look,
                breath=breath,
                blink=blink,
                lip_sync=lip_sync,
                desired=desired,
                final=final,
                owner=effective_parameter_owner(mode, parameter),
            )
        return contributions
