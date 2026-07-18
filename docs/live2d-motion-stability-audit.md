# Live2D motion stability audit

This document records the implementation contract and the evidence required to
accept a Live2D host render. It does not claim that the repository contains a
general-purpose Live2D editor.

## Scope and result

The defect existed in the original transparent WebM before Remotion was
involved. The old renderer allowed the model motion system, automatic breath,
procedural idle, procedural blink, and lip sync to write overlapping parameter
families. It also started the next motion immediately after
`IsMotionFinished()`. The resulting frame stream contained real parameter
discontinuities; browser playback and final encoding were not the primary
cause.

The production path now has:

- one typed owner for every controlled parameter;
- a staged update pipeline with one final parameter commit;
- explicit motion enter/play/exit/return/cooldown states;
- deterministic target-based idle, gaze, blink, breath, and lip-sync
  controllers;
- velocity, acceleration, jerk, reversal, and high-frequency gates;
- image-space centroid, alpha, face, eye, and perceptual-delta gates;
- a complete JSONL trace beside every accepted host WebM;
- fail-closed validation in the backend adapter.

## Root-cause answers

1. **Was the jitter already in the raw transparent WebM?** Yes. The legacy
   control experiment fails 38 parameter gates before compositing.
2. **Was it introduced only by Remotion or browser decoding?** No. Fixed
   background composition preserves the same legacy discontinuities. Real
   Microsoft Edge playback of the corrected host advances without console or
   decoding errors.
3. **Which controllers conflicted?** Motion files overlapped head, body, eye,
   eyelid, mouth, and breath parameters. AutoBreath and procedural breath both
   affected breath; procedural sine idle was added after motion; the old blink
   multiplied motion-owned eyelids; lip sync overwrote motion mouth values.
4. **Did motion switching jump?** Yes. The audited model can expose a raw
   source-pose gap above 20 parameter units. The final mixer limits the
   committed switch delta to a small fraction of the model range and returns
   through neutral/cooldown rather than chaining motions directly.
5. **Was mouth jitter caused by raw RMS?** Partly. The old one-stage envelope
   reached a maximum frame delta of about `0.389`. Robust calibration,
   hysteresis, minimum hold, dead zone, asymmetric attack/release, and
   kinematic limiting reduce the production maximum to roughly `0.07-0.08` on
   the diagnostic speech.
6. **Is time monotonic and FPS-aligned?** Yes. At 30 FPS the trace uses one
   monotonic frame clock and records 33-34 ms integer display deltas while the
   controller receives the exact `1/30` second delta.
7. **Are motion metadata and fades handled?** The worker reads the selected
   `.mtn` FPS, frame count, fade-in, and fade-out metadata. The state machine
   applies bounded enter/exit transitions and a minimum neutral/cooldown
   interval.
8. **Did VP9 alpha add extra jumps?** No evidence of that. The native capture
   verifies a varying alpha channel before encoding. PyAV may expose VP9 as
   `yuv420p`; the offline analyzer therefore records whether alpha was decoded
   or recovered from the stable background. The fixed-background comparison is
   the independent control.

## Production parameter ownership

| Parameter family | Final owner | Other inputs |
| --- | --- | --- |
| Head X/Y/Z | `motion_mixer` | motion pose plus low-weight idle target |
| Body X | `motion_mixer` | motion pose plus low-weight idle target |
| Eye ball X/Y | `eye_gaze_mixer` | weighted motion gaze and smooth look target |
| Eye open L/R | `blink_controller` | deterministic blink state only |
| Mouth open | `lip_sync_controller` | calibrated audio envelope only |
| Breath | `breath_controller` | low-amplitude continuous oscillator only |

Motion files are deliberately ignored for production eyelid, mouth, and breath
final values. Counterfactual experiment modes may expose the raw motion values,
but production validation requires the ownership table above.

## Control stages

```text
monotonic time
  -> motion sample
  -> motion transition state and blend
  -> procedural idle/look/breath targets
  -> blink state machine
  -> lip-sync state machine
  -> typed parameter mixer
  -> range and derivative constraints
  -> one final SetParameterValue commit
  -> draw, encode, image diagnostics, JSONL trace
```

No controller relies on call order as an undocumented priority mechanism.
Every trace row contains the source contributions, desired value, final value,
and owner.

## Four isolation experiments

All modes use the same Soyo Cubism 2 model, the same 16.63-second PCM speech,
720x720 output, 30 FPS, emotion, and deterministic seed.

| Mode | Purpose | Expected interpretation |
| --- | --- | --- |
| `motion_only` | Model motion plus smooth lip sync | Reveals defects inherent in motion curves |
| `procedural_only` | Neutral pose, idle, gaze, blink, breath, lip sync | Validates procedural controllers without motion |
| `no_lip_sync` | Complete final system with mouth disabled | Separates mouth motion from whole-body motion |
| `final` | Production candidate | Must pass every parameter and image gate |
| `legacy_conflict` | Reproduction-only control | Must reproduce the old conflict architecture |

The repeatable command is:

```powershell
uv run python scripts/run_live2d_ab_experiments.py `
  --model "<DSAKIKO_ROOT>\live2d_related\soyo\live2D_model\3.model.json" `
  --audio "<DIAGNOSTIC_PCM_WAV>" `
  --live2d-python "<DSAKIKO_ROOT>\runtime\python.exe" `
  --ffmpeg "<DSAKIKO_ROOT>\GPT_SoVITS\ffmpeg.exe" `
  --output-root "<NEW_OUTPUT_DIRECTORY>" `
  --duration-ms 16630 --width 720 --height 720 --fps 30 `
  --emotion happiness --seed 20260717 --include-legacy
```

The runner saves transparent WebM, fixed-background MP4, full JSONL traces,
decoded-video analysis, 20-point contact sheets, and three two-second
60-frame sequences for silence, speech, and motion transition.

## Gate rationale

Thresholds are calculated from the real Cubism parameter range and frame rate,
then calibrated against the legacy and corrected A/B traces. They are grouped
by head, body, gaze, eyelid, mouth, and breath because a natural blink needs
different derivatives from a head turn.

The acceptance gate checks:

- maximum and p95/p99 per-frame step;
- velocity, acceleration, and jerk;
- direction reversals per second;
- high-frequency energy;
- raw source-pose and committed motion-switch gaps;
- alpha area and centroid changes;
- decoded perceptual, face-region, and eye-region deltas;
- repeated-frame ratio and longest frozen run.

The thresholds are not relaxed when a candidate fails. The controller is
changed and the full experiment is rerun.

## AIRI and DSakiko research

AIRI was inspected as an architectural reference only:

- source: <https://github.com/moeru-ai/airi>
- audited revision: `0c2932679c98dc230733a77040dcfaa39cc4be27`
- license: MIT

Relevant public concepts were true delta time, staged updates, handled state,
semi-implicit Euler integration, spring damping, blink states, smooth gaze
targets, controller enable/disable, max FPS, and render scale. No AIRI source
code was copied.

The local DSakiko installation was read but not modified. The audited model
motions are 30 FPS and include fade metadata. DSakiko exposes motion preview
and parameter controls in its GUI code, and enables native auto blink/breath
in its interactive path. The god-news worker disables native auto breath in
the corrected production path and owns those parameters explicitly.

## Browser and final-video acceptance

Template Lab production visual tests no longer skip host cases. A missing real
host WebM fails the suite. The test plays the horizontal and vertical
compositions, verifies at least two seconds of frame advancement, hashes
multiple decoded frames, pauses, advances one frame, resumes, and rejects
console/media errors.

The complete E2E command is:

```powershell
uv run python scripts/run_e2e_video.py `
  --dsakiko-root "<DSAKIKO_ROOT>" `
  --live2d-size 720 --live2d-fps 30 `
  --source-duration-seconds 12 `
  --render-timeout-seconds 3600 --render-concurrency 2 `
  --render-attempts 2
```

Its artifact report records the source Git commit, role and TTS evidence, each
host trace, dual-profile render metadata, semantic story samples, uniform
20-point sheets, three 60-frame final-MP4 sequences, and an aligned comparison
of the raw host WebM, fixed-background host MP4, and both Remotion outputs.

## Template status

The template infrastructure is versioned and production-validated, but the
current formal catalog contains exactly:

- 1 template: `world_warmth@1.0.0`;
- 4 scene variants: `host_split_editorial`,
  `host_corner_full_bleed`, `evidence_documentary`, and
  `source_video_clean`;
- 2 output profiles: Douyin vertical and Bilibili horizontal.

Additional templates remain future extension points. This audit does not
describe the current catalog as a complete multi-template library.

## Tooling note

The real browser workflow was verified through Playwright using the installed
Microsoft Edge channel. Windows computer control was also available for final
desktop playback inspection. No claim is made that the DSakiko GUI itself was
operated: its packaged entry point is a batch launcher, and safe desktop
automation does not execute terminal or batch commands through the UI. Its
motion, priority, fade, blink, breath, look, preview, and parameter behavior was
therefore audited from the installed source and model files. Native OpenGL
rendering, real model files, continuous decoded frames, browser playback, and
desktop playback provide the executable acceptance evidence.
