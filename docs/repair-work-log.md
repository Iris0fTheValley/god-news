# 2026-07 production repair work log

This log records evidence for the repair objective that starts from
`codex/live2d-motion-stability` at
`bc724b6fcfc1d9b857275edcf2af500d062d5939`.

## Acceptance scope

- Keep the backend OpenAPI document as the only API contract source and prove generated
  frontend artifacts do not drift.
- Make the story queue and video batch workflows work against persisted backend data,
  including legacy or invalid records, without hiding failures.
- Expose the operator-facing collection, review, batch, rendering, scene, and Live2D
  diagnostics needed to run the production workflow.
- Run at least one real network connector and take at least three real stories through
  the UI-backed workflow to real 16:9 and 9:16 outputs.
- Preserve complete provenance and rights evidence for every network visual asset. Unknown
  rights must never become publish eligible.
- Replace the broad Template Lab meaning with a production-component Scene/Visual System
  Lab.
- Locate and remove visible Live2D stutter, then verify the raw host render, fixed-background
  render, Scene Lab playback, and both final output profiles.

## Baseline evidence

Recorded on 2026-07-29 (Asia/Hong_Kong).

- Branch and commit match the requested baseline.
- Production backend and frontend start successfully through `scripts/start.ps1`; health,
  story-list, and video-batch-list requests currently return HTTP 200.
- The story queue renders 50 persisted records, but the visible records are repeated
  `self-authored-e2e-source` fixtures rather than evidence from a live network collection.
- The source page reports `0/4` authorized collectors. Reddit is enabled but unconfigured,
  and its OAuth diagnostic action is disabled.
- Historical production backend evidence contains a story-list failure caused by persisted
  `ScriptPreferences` that no longer validated (`spoken_language`, `caption_language`, and
  an 8-second duration). It also contains video-batch conflict responses. Current list
  success therefore does not prove legacy-record compatibility or a complete batch flow.
- Template Lab uses a local production Remotion composition but logged
  `EncodingError: The source image cannot be decoded` for the default source screenshot.
- Freshly exported `frontend/openapi.json` and `frontend/src/api/generated.ts` have exactly
  the same SHA-256 hashes as their tracked counterparts. CI already includes a generated
  contract drift check.
- Existing automated baseline:
  - backend: 252 tests passed;
  - Ruff: passed;
  - mypy (122 source files): passed;
  - frontend: lint/typecheck and 28 tests passed;
  - video: typecheck, 29 tests, and Remotion bundle passed.
- Existing end-to-end media is driven by a self-authored fixture pool. It is useful as a
  renderer diagnostic but is not evidence for the required real-network workflow.
- Machine `PATH` does not currently expose standalone `ffmpeg` or `ffprobe`; the repository
  has Remotion-bundled media tooling and separately configurable production quality tooling.

## Current phase

The typed source-connector boundary and three-story review/TTS slice are complete. Work is now
focused on rights-aware Wikimedia Commons acquisition, a separate muted B-roll contract, the
production Scene/Visual System Lab, and the final dual-profile batch.

## Completed live connector slice

- Added a provider-neutral `SourceConnector` registry and typed request, attempt, error,
  snapshot, rights, media-candidate, article, and discovery-result contracts.
- Added the official, credential-free NASA RSS connector and a compatibility adapter for the
  existing source-run ingestion pipeline. The connector records response byte count and SHA-256,
  supports cursors, classifies retry attempts, and keeps per-media rights fail-closed because
  NASA pages may contain third-party media.
- Removed fixed four-source counts from backend readiness/rate-limit paths and from the source
  UI. `SOURCE_ORDER` is now the compatibility registry for the five active collectors.
- Restarted the production services and ran NASA through the real Source Runs UI. Run
  `2026-07-28T18:14:44.973848Z` to `2026-07-28T18:15:40.563569Z` discovered and ingested five
  stories with zero failures or duplicates. The UI displayed the sanitized current URL and
  live counters.
- Verified the five persisted stories in the real story queue as `source-contract:nasa`,
  translated to `zh-CN`, and waiting at `PENDING_FIRST_REVIEW`.
- Captured browser evidence at:
  - `output/playwright/real-nasa-source-run.png`
  - `output/playwright/real-nasa-story-queue.png`
- Focused connector/API tests, Ruff, mypy, frontend typecheck, and the complete 30-test frontend
  suite pass after this slice.

## Rights-aware visual research evidence

- The official Wikimedia Commons API returns per-file `extmetadata`, canonical file-page URLs,
  direct downloads, dimensions, hashes, and timed-media derivatives.
- Live queries found Public Domain NASA raster images and video candidates. TimedMedia returns
  Ogg/WebM originals and VP9 WebM derivatives for the chosen candidates; no MP4 derivative is
  available, so the existing MP4-only source-media store cannot truthfully accept them without
  a typed format/transformation change.
- The planned acquisition boundary will persist the Commons file page, creator, license name
  and URL, attribution, source hash, selected derivative, retrieved hash, and transformation
  evidence. UI-supplied license fields will not be trusted.

## Completed three-story review and TTS slice

- Three stories from the live NASA source run were approved through the real browser UI,
  generated as structured Japanese spoken text with matched Chinese translation captions,
  reviewed at the script gate, synthesized by the local DSakiko Soyo GPT-SoVITS weights, and
  frozen at final review:
  - `21479274-06b4-42ca-8f3d-2ecdc6cbba63`: 3 clips, 33,440 ms;
  - `9a3802d4-85d8-4a12-bcd0-1130a4bdb54f`: 3 clips, 25,660 ms;
  - `ac1c61b1-74d1-46fe-a891-edaf0c144597`: 4 clips, 33,720 ms.
- The second story exposed a real Windows-only failure: GPT-SoVITS ran under Python isolated
  mode and attempted to encode the Japanese middle dot in an inherited GBK runtime. The vendor
  returned HTTP 400 with `gbk codec can't encode character '\u30fb'`.
- The child runtime now receives the explicit Python `-X utf8` switch, which remains effective
  under `-I`. The adapter also surfaces a bounded, path/secret-redacted vendor `Exception`
  field instead of hiding the actionable cause behind `tts failed`.
- The unchanged story was retried through the UI and all three clips succeeded; a third story
  with four clips then succeeded on the same fixed runtime. Focused regression tests cover the
  isolated UTF-8 command and vendor-detail redaction.
- Captured the real NASA source page in the in-app browser and registered the validated JPEG
  through the existing application service as source-page evidence:
  - local audit capture: `output/e2e-real/nasa-source-screenshot.jpg`;
  - stored asset: `e6674bef-4061-4042-9ddc-c0712971cb6e`;
  - SHA-256: `d901ec8675c49f9b0b6f61ab7ab8494bf3ddddaa1b26d550f98de3cf42bd3bd5`;
  - canonical source: `https://www.nasa.gov/image-article/nasa-astronaut-chris-williams-returns-to-earth/`.

## Assumptions

- Existing untracked root-level Codex/network diagnostic PowerShell files, `nul`, and
  `scripts/_test_sources.cmd` belong to the user and are out of scope. They will not be
  modified, staged, or deleted.
- Missing Reddit credentials are an external readiness fact, not a reason to fabricate
  OAuth success or block work on another lawful public connector.

## Active blockers

- Reddit has no configured client credentials in the current local environment.
- Final dual-profile render and media inspection remain unfinished.

## Commons, B-roll, and real batch integration

- Added a fail-closed Wikimedia Commons boundary with official API search, exact server-side
  re-resolution, descriptive API/download User-Agent, bounded streaming download, SHA-256,
  raster decoding or ffprobe, story/script/segment binding, and explicit operator approval.
- A live mixed-media query exposed and fixed search-result isolation: exploratory searches now
  omit unsupported records while exact File/page resolution still fails closed.
- Through the production frontend, staged and approved the NASA Public Domain timed-media file
  `File:Moon transit of sun large.ogv` for story
  `9a3802d4-85d8-4a12-bcd0-1130a4bdb54f`, segment 1:
  - Commons page ID `4250664`;
  - local asset ID `7adeebd2-9664-4799-9635-9f32689ab8a5`;
  - downloaded SHA-256 prefix `33438879de75e4f0`;
  - ffprobe duration about 8.0 seconds;
  - source attribution `NASA`, license `Public domain`.
- The approved candidate is adapted behind an independent `BrollVideoAssetLibrary`; it remains
  muted, revision-bound, rights-attributed, and byte-verified at batch freeze and render time.
- Remotion now has a dedicated responsive B-roll scene using the shared semantic plan for both
  output profiles. It never reuses the transcript-reviewed original-source-video contract.
- The frontend Scene / Visual System Lab now previews the production player and registered
  template/layout system, exposes slots/safe areas/media-fit/assets, and passed desktop/mobile
  Playwright checks. Evidence: `output/playwright/scene-visual-system-lab.png`.
- Created batch `93d4fb7b-0adc-4b0a-885e-83acf872a242` through the real frontend using the three
  reviewed NASA stories. The director preserved ten source segments and generated two reviewed
  Japanese/Chinese transition segments.
- The first batch attempt completed 12 GPT-SoVITS clips and 12 transparent Live2D host renders,
  then exposed an over-strict legacy rule requiring a unique visual for every narration segment.
  The guard now requires at least one reviewed visual/video at batch level, allowing deterministic
  template fallback for bridges and other intentionally asset-free narration scenes.

## Next evidence

1. Complete the retried batch freeze, timeline approval, and both Remotion renders.
2. Inspect output streams, representative frames, captions, attribution, B-roll, and Live2D
   enter/exit behavior.
3. Re-run the Live2D isolation evidence against the final player and outputs, then complete the
   independent release review.

## Versioned template and production render retry

- Added the explicit `host_only_editorial` scene variant for narration that intentionally has
  no evidence asset. The resolver now selects only a registered variant whose host and asset
  capabilities match the frozen scene; it no longer mutates the default variant contract.
- Bumped the shared Python/TypeScript/frontend template contract to
  `world_warmth@1.1.0`. The incompatible pre-change batch was deleted through the official API,
  then the replacement batch `622df081-2040-4018-82ce-a1dd2197f40f` was created through the
  production frontend with the three reviewed NASA stories.
- The replacement batch completed 12 real GPT-SoVITS clips and 12 transparent Live2D host
  renders (103,540 ms total narration), froze 13 scenes, and passed the human narration and
  timeline gates through the production UI. Its scene mix is nine host-only scenes, three
  host/evidence scenes, and one attributed Commons B-roll scene.
- Renderer readiness now discovers Remotion's bundled `ffprobe`, while the configurable quality
  `ffmpeg` must be a full build with `blackdetect` and `freezedetect`; the stripped compositor
  binary is no longer silently accepted as a quality tool.
- A real first-profile render exposed that the previous hard-coded four-second freeze gate
  misclassified the approved eight-second, very-low-motion astronomical B-roll. The maximum
  allowed detected freeze is now a typed environment setting (12 seconds by default), while
  longer stalls still fail with the observed and configured durations in the diagnostic.
- The same frozen input then rendered successfully through the official batch renderer:
  - Douyin: 1080x1920, H.264/AAC, 30 fps, 117.461 s, 26,548,053 bytes;
  - Bilibili: 1920x1080, H.264/AAC, 30 fps, 117.461 s, 31,251,706 bytes.
- Both outputs have zero black segments, aligned audio/container durations (61 ms delta), and
  pass the configured freeze gate. Representative frames confirm responsive host-only and
  host/evidence layouts, readable Chinese captions, the NASA source screenshot, and source
  attribution.
- Final regression evidence: 278 backend tests, 32 frontend tests and production build,
  31 video tests and Remotion bundle, mypy, Ruff, and 10 real-WebM desktop/mobile Playwright
  Scene Lab cases all pass.
