from __future__ import annotations

import math
from itertools import pairwise

import pytest

from god_news.live2d_control import (
    CONTROLLED_PARAMETERS,
    PARAM_ANGLE_X,
    PARAM_BODY_ANGLE_X,
    PARAM_BREATH,
    PARAM_EYE_BALL_X,
    PARAM_EYE_BALL_Y,
    PARAM_EYE_L_OPEN,
    PARAM_EYE_R_OPEN,
    PARAM_MOUTH_OPEN_Y,
    PARAMETER_OWNERS,
    BlinkController,
    BlinkState,
    KinematicLimiter,
    Live2DControlMode,
    MotionState,
    MotionTransitionController,
    MouthController,
    MouthSettings,
    ParameterMixer,
    ParameterOwner,
    ParameterRange,
    ProceduralPoseController,
    SpringDamper,
    SpringSettings,
    effective_parameter_owner,
)


def _ranges() -> dict[str, ParameterRange]:
    return {
        PARAM_ANGLE_X: ParameterRange(-30, 30, 0),
        "PARAM_ANGLE_Y": ParameterRange(-30, 30, 0),
        "PARAM_ANGLE_Z": ParameterRange(-30, 30, 0),
        PARAM_BODY_ANGLE_X: ParameterRange(-10, 10, 0),
        PARAM_EYE_BALL_X: ParameterRange(-1, 1, 0),
        PARAM_EYE_BALL_Y: ParameterRange(-1, 1, 0),
        PARAM_EYE_L_OPEN: ParameterRange(0, 1.5, 1),
        PARAM_EYE_R_OPEN: ParameterRange(0, 1.5, 1),
        PARAM_MOUTH_OPEN_Y: ParameterRange(0, 1, 0),
        PARAM_BREATH: ParameterRange(0, 1, 0),
    }


def test_spring_damper_converges_without_overshoot_when_critically_damped() -> None:
    spring = SpringDamper(0)
    values = [
        spring.update(
            1,
            delta_seconds=1 / 60,
            settings=SpringSettings(
                frequency_hz=1.2,
                damping_ratio=1,
                maximum_velocity=5,
                maximum_acceleration=30,
            ),
        )
        for _ in range(240)
    ]

    assert all(left <= right + 1e-9 for left, right in pairwise(values))
    assert values[-1] == pytest.approx(1, abs=1e-5)


def test_spring_damper_handles_irregular_delta_time_like_regular_steps() -> None:
    regular = SpringDamper(0)
    irregular = SpringDamper(0)
    settings = SpringSettings(
        frequency_hz=0.8,
        damping_ratio=1.05,
        maximum_velocity=4,
        maximum_acceleration=20,
    )
    for _ in range(300):
        regular.update(0.7, delta_seconds=1 / 60, settings=settings)
    pattern = [0.011, 0.022, 0.007, 0.027]
    elapsed = 0.0
    index = 0
    while elapsed < 2:
        step = min(pattern[index % len(pattern)], 2 - elapsed)
        irregular.update(0.7, delta_seconds=step, settings=settings)
        elapsed += step
        index += 1

    assert irregular.value == pytest.approx(regular.value, abs=0.012)
    assert irregular.velocity == pytest.approx(regular.velocity, abs=0.03)


def test_blink_controller_uses_complete_deterministic_state_machine() -> None:
    left = BlinkController(seed=9)
    right = BlinkController(seed=9)
    states: set[BlinkState] = set()
    track: list[float] = []
    for _ in range(360):
        track.append(left.update(1 / 60))
        right_value = right.update(1 / 60)
        states.add(left.state)
        assert right_value == track[-1]
        assert right.state is left.state

    assert {
        BlinkState.WAITING,
        BlinkState.CLOSING,
        BlinkState.CLOSED,
        BlinkState.OPENING,
        BlinkState.RECOVERY,
    }.issubset(states)
    assert min(track) == 0
    assert max(track) == 1


def test_mouth_gate_hysteresis_does_not_chatter_near_threshold() -> None:
    controller = MouthController(
        MouthSettings(noise_floor=0, normalization_peak=1, minimum_hold_seconds=0.1)
    )
    frames = []
    for value in [0.0, 0.07, 0.045, 0.035, 0.045, 0.005, 0.005, 0.005, 0.005]:
        frames.append(controller.update(value, delta_seconds=1 / 30))

    assert frames[1].gate_open
    assert all(frame.gate_open for frame in frames[2:5])
    assert not frames[-1].gate_open
    assert sum(
        left.gate_open != right.gate_open
        for left, right in pairwise(frames)
    ) == 2


def test_mouth_attack_is_faster_than_release_and_silence_reaches_zero() -> None:
    controller = MouthController(MouthSettings(noise_floor=0, normalization_peak=1))
    attack = [
        controller.update(0.8, delta_seconds=1 / 60).final_value
        for _ in range(12)
    ]
    release = [
        controller.update(0, delta_seconds=1 / 60).final_value
        for _ in range(60)
    ]

    assert attack[-1] > 0.45
    assert release[3] > 0
    assert release[-1] == 0
    assert attack[3] - attack[0] > release[0] - release[3]


@pytest.mark.parametrize(
    ("name", "envelope", "minimum_peak", "maximum_peak"),
    [
        ("silence", [0.0] * 90, 0.0, 0.0),
        ("white_noise", [0.008, 0.006, 0.009] * 30, 0.0, 0.0),
        ("single_plosive", [0.0] * 15 + [0.3] + [0.0] * 44, 0.0, 0.25),
        ("sustained_vowel", [0.0] * 5 + [0.2] * 35 + [0.0] * 30, 0.45, 1.0),
        (
            "normal_speech",
            [0.0, 0.04, 0.11, 0.18, 0.12, 0.05, 0.0] * 12,
            0.25,
            1.0,
        ),
        (
            "fast_speech",
            [0.02, 0.14, 0.03, 0.17, 0.02, 0.12] * 14,
            0.2,
            1.0,
        ),
        ("low_volume_speech", [0.0] * 5 + [0.045] * 35 + [0.0] * 30, 0.1, 0.8),
    ],
)
def test_mouth_controller_handles_required_audio_profiles(
    name: str,
    envelope: list[float],
    minimum_peak: float,
    maximum_peak: float,
) -> None:
    controller = MouthController(
        MouthSettings(noise_floor=0.01, normalization_peak=0.3)
    )
    track = [
        controller.update(value, delta_seconds=1 / 30).final_value
        for value in envelope
    ]

    assert max(track) >= minimum_peak, name
    assert max(track) <= maximum_peak, name
    assert all(0 <= value <= 1 for value in track)
    assert max(abs(right - left) for left, right in pairwise(track)) <= 0.24
    if all(value == 0 for value in envelope[-10:]):
        assert track[-1] == pytest.approx(0, abs=0.02)


def test_kinematic_limiter_enforces_velocity_acceleration_and_jerk() -> None:
    limiter = KinematicLimiter(0)
    values: list[float] = []
    velocities: list[float] = []
    accelerations: list[float] = []
    for _ in range(300):
        values.append(
            limiter.update(
                1,
                delta_seconds=1 / 60,
                maximum_velocity=0.8,
                maximum_acceleration=3,
                maximum_jerk=18,
            )
        )
        velocities.append(limiter.velocity)
        accelerations.append(limiter.acceleration)

    assert max(abs(value) for value in velocities) <= 0.8 + 1e-9
    assert max(abs(value) for value in accelerations) <= 3 + 1e-9
    jerks = [
        (right - left) * 60
        for left, right in pairwise(accelerations)
    ]
    assert max(abs(value) for value in jerks) <= 18 + 1e-9
    assert values[-1] == pytest.approx(1, abs=1e-4)


def test_motion_transition_never_restarts_directly_after_finish() -> None:
    controller = MotionTransitionController()
    first = controller.update(
        delta_seconds=1 / 30,
        motion_finished=False,
        motion_available=True,
    )
    assert first.start_motion
    states = [first.state]
    starts = 1
    for frame in range(240):
        result = controller.update(
            delta_seconds=1 / 30,
            motion_finished=frame >= 45,
            motion_available=True,
        )
        states.append(result.state)
        starts += int(result.start_motion)

    assert MotionState.EXITING in states
    assert MotionState.RETURNING_TO_NEUTRAL in states
    assert MotionState.COOLDOWN in states
    assert starts >= 2
    first_exit = states.index(MotionState.EXITING)
    second_enter = states.index(MotionState.ENTERING, first_exit + 1)
    assert MotionState.RETURNING_TO_NEUTRAL in states[first_exit:second_enter]
    assert MotionState.COOLDOWN in states[first_exit:second_enter]


def test_parameter_ownership_is_total_and_unique() -> None:
    assert set(PARAMETER_OWNERS) == set(CONTROLLED_PARAMETERS)
    assert PARAMETER_OWNERS[PARAM_MOUTH_OPEN_Y] is ParameterOwner.LIP_SYNC_CONTROLLER
    assert PARAMETER_OWNERS[PARAM_EYE_L_OPEN] is ParameterOwner.BLINK_CONTROLLER
    assert PARAMETER_OWNERS[PARAM_EYE_BALL_X] is ParameterOwner.EYE_GAZE_MIXER
    assert PARAMETER_OWNERS[PARAM_ANGLE_X] is ParameterOwner.MOTION_MIXER
    assert effective_parameter_owner(
        Live2DControlMode.MOTION_ONLY,
        PARAM_EYE_L_OPEN,
    ) is ParameterOwner.MOTION_SAMPLER
    assert effective_parameter_owner(
        Live2DControlMode.PROCEDURAL_ONLY,
        PARAM_ANGLE_X,
    ) is ParameterOwner.PROCEDURAL_POSE_MIXER
    assert effective_parameter_owner(
        Live2DControlMode.NO_LIP_SYNC,
        PARAM_MOUTH_OPEN_Y,
    ) is ParameterOwner.NEUTRAL_MOUTH_CONTROLLER


def test_parameter_mixer_enforces_production_parameter_ownership() -> None:
    ranges = _ranges()
    mixer = ParameterMixer(ranges)
    pose = ProceduralPoseController(seed=4).update(
        timestamp_seconds=1,
        delta_seconds=1 / 30,
        motion_weight=1,
    )
    values = mixer.mix(
        delta_seconds=1 / 30,
        mode=Live2DControlMode.FINAL,
        base_values={parameter: value.default for parameter, value in ranges.items()},
        motion_values={
            PARAM_ANGLE_X: 12,
            PARAM_EYE_BALL_X: 0.7,
            PARAM_EYE_L_OPEN: 1.5,
            PARAM_BREATH: 0.95,
        },
        motion_weight=1,
        procedural_pose=pose,
        blink_openness=0,
        blink_owned=False,
        mouth_value=0.6,
    )

    assert values[PARAM_ANGLE_X].desired == pytest.approx(
        12 + pose.idle[PARAM_ANGLE_X]
    )
    assert abs(pose.idle[PARAM_ANGLE_X]) < 0.02
    assert values[PARAM_EYE_BALL_X].desired == pytest.approx(0.7)
    assert values[PARAM_MOUTH_OPEN_Y].desired == pytest.approx(0.6)
    assert values[PARAM_EYE_L_OPEN].desired == pytest.approx(0)
    assert values[PARAM_BREATH].desired == pytest.approx(pose.breath)
    assert values[PARAM_EYE_L_OPEN].owner is ParameterOwner.BLINK_CONTROLLER

    without_lip_sync = mixer.mix(
        delta_seconds=1 / 30,
        mode=Live2DControlMode.NO_LIP_SYNC,
        base_values={parameter: value.default for parameter, value in ranges.items()},
        motion_values={PARAM_MOUTH_OPEN_Y: 1},
        motion_weight=1,
        procedural_pose=pose,
        blink_openness=1,
        blink_owned=True,
        mouth_value=0.8,
    )
    assert without_lip_sync[PARAM_MOUTH_OPEN_Y].desired == pytest.approx(
        ranges[PARAM_MOUTH_OPEN_Y].default
    )


def test_procedural_pose_is_seeded_and_stable_across_frame_rates() -> None:
    at_30 = ProceduralPoseController(seed=123)
    at_60 = ProceduralPoseController(seed=123)
    pose_30 = None
    pose_60 = None
    for frame in range(90):
        pose_30 = at_30.update(
            timestamp_seconds=(frame + 1) / 30,
            delta_seconds=1 / 30,
            motion_weight=0,
        )
    for frame in range(180):
        pose_60 = at_60.update(
            timestamp_seconds=(frame + 1) / 60,
            delta_seconds=1 / 60,
            motion_weight=0,
        )

    assert pose_30 is not None and pose_60 is not None
    for parameter in pose_30.idle:
        assert pose_30.idle[parameter] == pytest.approx(
            pose_60.idle[parameter],
            abs=0.04,
        )
    for parameter in pose_30.look:
        assert pose_30.look[parameter] == pytest.approx(
            pose_60.look[parameter],
            abs=0.008,
        )
    assert math.isfinite(pose_30.breath)
