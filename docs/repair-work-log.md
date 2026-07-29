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

The real-network three-story slice, rights-aware visual acquisition, local multilingual
TTS/Live2D production, responsive dual-profile render, media inspection, and independent release
review are complete. The current release artifact is the immutable v1.6 batch documented below.

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
- This verified technical pilot is about 117 seconds, not the future five-minute editorial
  target. No looping or artificial padding was added to misrepresent the available reviewed
  material.

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

No release-blocking verification remains for the technical pilot. A later five-minute editorial
episode should add more independently reviewed stories rather than loop or pad this cut.

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
  misclassified approved low-motion editorial scenes. The maximum allowed detected freeze is
  now a typed environment setting (15 seconds by default), while
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

## Independent release review

- The independent reviewer found a release-blocking rights downgrade in the NASA compatibility
  adapter: article-level NASA public-domain policy could replace an embedded media candidate's
  unknown rights. The adapter now collapses the story/media rights to `unknown`, non-publishable
  whenever any retained media candidate requires review. The connector-to-collector regression
  test proves this fail-closed result.
- Commons staging now computes SHA-1 over the downloaded bytes and compares it with the official
  API metadata snapshot before media probing or persistence. A mismatch test proves that the
  downloaded file is removed and never enters review.
- Python now validates each scene variant's host slot and support for every requested output
  profile before render, matching the TypeScript contract instead of deferring failure to the
  renderer.
- After these release fixes, the complete backend suite passes with 279 tests, plus Ruff and
  mypy.

## Final all-material editorial cut

- Completed-batch story claims are now treated as active production reservations rather than
  permanent ownership. A rendered batch remains immutable audit evidence, while its stories can
  be selected for a later editorial cut. Repository queries ignore completed reservations and
  lazily remove legacy completed markers before creating a new batch; focused SQL tests prove
  that an overlapping active batch still conflicts while a completed batch does not.
- The production batch boundary now adapts approved, current-revision Commons images as immutable
  `VisualRenderAsset` snapshots in addition to editor uploads and source-page screenshots.
  Publish eligibility, operator approval, script revision, segment binding, local bytes, hash,
  dimensions, canonical Commons page, attribution, and license label are preserved. A focused
  test proves that an approved Commons image enters the exact narration segment snapshot.
- Through the production visual-discovery API, staged and approved
  `File:Christopher Williams.jpg` for the first NASA story:
  - asset ID `8b7e9db8-2435-4cc7-a87e-02cbf180f7ae`;
  - story `ac1c61b1-74d1-46fe-a891-edaf0c144597`;
  - segment `423d6ae9-7867-4b6a-a2c4-363de5a33547`;
  - creator `Robert Markowitz`, license `Public domain`;
  - downloaded SHA-256
    `762e2a3b19564c2b2cb07fc761d50117cf2d2dbbc8f4e4fd6fb16a3b9c701a44`;
  - official Commons SHA-1 `2c18dc2e64c1c8e02ec0b3c517395780bcf06e34`, verified against
    the downloaded bytes.
- The first post-discovery batch exposed that approved Commons images were not yet consumed by
  the video library. It was cancelled through the production frontend after timeline generation,
  the missing adapter was implemented and tested, and a fresh immutable batch was created rather
  than mutating audit evidence.
- Final batch `60aa0daf-13f1-4e99-9d36-0f57b3d7a0c0` was created, narration-approved, synthesized,
  and timeline-approved through the production frontend. Its frozen input hash is
  `6f810b18351da1426a1f0b5abf3e780b1af81e6979fe273431284be6dada5142`.
  The frozen inputs contain 12 audio clips, 12 transparent Live2D host videos, the Commons
  portrait, the NASA source-page screenshot, and the approved Commons astronomical B-roll.
  The first story scene references the portrait, the second story inserts B-roll with the host
  hidden, and the third story references the source screenshot.
- Visual QA for the preceding byte-equivalent content cut includes two 20-point contact sheets
  and three continuous three-second/12-frame windows at approximately 5, 52, and 100 seconds.
  All three windows were inspected and show controlled pose, mouth, and blink changes without
  visible periodic jitter, frozen animation, host cropping, or broken evidence composition.

## Contextual-rights release iteration (superseded by v1.6)

- The preceding batch revealed a contextual-provenance defect: the verified NASA public-domain
  B-roll bytes had been approved for the astronaut-return story but visually belonged with the
  eclipse story. Approved discovery assets can now be cloned through the production API without
  another network download. The clone receives a unique storage key and byte/hash verification,
  but remains `STAGED` until an operator separately approves its new story, script
  revision, segment, and editorial context.
- The public-domain Moon-transit video was reused and explicitly approved for the eclipse story
  as asset `2a0dd8f9-0d24-4915-955d-c11284641eea`; its bytes remain
  `33438879de75e4f0fd4388fc5150faaad1002f508cd45ed2b212227cf535897f`
  (8,078,924 bytes). This keeps acquisition provenance reusable while making editorial approval
  contextual and fail-closed.
- Final batch `f0c66cf7-4f7f-41f9-8180-7a640f9801b9` was created, narration-approved,
  synthesized, timeline-approved, started, monitored, and confirmed complete through the
  production frontend. Its immutable input hash is
  `87c5ddfae732c1232a6d6a81a8bc4cba4220f88fa678d16731600098afed5d70`.
  The 27 frozen inputs contain 12 GPT-SoVITS clips, 12 transparent Live2D clips, the approved
  Commons portrait, the NASA source-page screenshot, and the contextually approved B-roll.
  Every one of the three real NASA stories therefore has at least one reviewed visual.
- The final deterministic outputs are:
  - Douyin: 1080x1920, H.264/AAC, 30 fps, 116.715 s, 28,915,034 bytes,
    SHA-256 `81e8445fbf8186386f4f71da1c104671cb125c251067ebc04c77d02b46a86a7f`;
  - Bilibili: 1920x1080, H.264/AAC, 30 fps, 116.715 s, 33,431,787 bytes,
    SHA-256 `0a81f60fb88a47026b4989f333878c9dcb8e93b233a71637c583f5159b86e521`.
- Independent ffprobe confirms both video/audio streams and dimensions. Both outputs have zero
  detected black segments. Their longest freeze candidates are 9.53 seconds and 4.67 seconds,
  below the 15-second gate. The vertical candidate is a known low-motion false positive:
  continuous-frame inspection shows ongoing Live2D pose, mouth, and blink changes.
- Final visual evidence lives in `output/e2e-real/final-qa-v14`: both 20-point contact sheets and
  three inspected three-second/12-frame windows at 5, 58, and 100 seconds. These cover the
  Commons portrait, moving public-domain eclipse B-roll, NASA webpage screenshot, Live2D motion,
  Chinese translated captions, responsive layouts, source attribution, and closing frame.
- Final automated verification passes: 280 backend tests, Ruff, mypy, 32 frontend tests plus
  lint/typecheck/production build, 31 video tests plus typecheck/Remotion bundle, and 10
  desktop/mobile Playwright Scene Lab cases using a real final-batch Live2D WebM.

## Final static-evidence correction and v1.6 release

- Independent visual review of the v1.4/v1.5 iterations found that the Commons portrait carried
  EXIF orientation metadata. The encoded pixel dimensions appeared portrait while browsers
  displayed the image landscape; the previous aspect-ratio heuristic therefore selected
  `cover` and cropped reviewed evidence differently between outputs.
- Reviewed static evidence now always uses `contain`, with evidence zoom disabled. This is a
  deliberate semantic boundary: without a reviewed focal-point contract, the renderer must not
  silently discard image or source-screenshot pixels. Motion footage keeps its profile-aware
  fill behavior. Focused TypeScript tests lock both static asset kinds to this policy.
- A fresh immutable batch was used instead of overwriting audit evidence. Batch
  `ca9d5861-8fad-44e4-8871-b61bfd6ead5f` was created, narration-approved, synthesized,
  timeline-approved, started, monitored, and confirmed complete through the production
  frontend. Its frozen render-input SHA-256 is
  `50f8fd03e15dbd5dd035dabb87f7bc94371d5e4bbd287d2d4da12dfc1c987bf5`.
- The final deterministic outputs are in
  `outputs/video-renders/ca9d5861-8fad-44e4-8871-b61bfd6ead5f/attempt-tnzuikrn`:
  - Douyin: 1080x1920, H.264/AAC, 30 fps, 116.886 s, 22,381,462 bytes,
    SHA-256 `c0d285ece38465d6121fa4216f2f2f7e0fb35d3564ed2c7baa30eef65615f9fd`;
  - Bilibili: 1920x1080, H.264/AAC, 30 fps, 116.886 s, 27,184,094 bytes,
    SHA-256 `70518fc3380c8a210389dad39f47843fb65906f4b7a21a3ca5f7ce01e1daa2fe`.
- Independent ffprobe confirms H.264 video, AAC stereo audio at 48 kHz, exact profile
  dimensions, and aligned durations. Independent FFmpeg analysis found zero black segments,
  longest freeze candidates of 3.23 seconds vertical and 2.00 seconds horizontal, mean volume
  -22.0 dB, and peak volume -3.4 dB.
- Final visual evidence is in `output/e2e-real/final-qa-v16`. Both 20-point sheets and three
  continuous three-second/12-frame windows were inspected: the portrait at 4 seconds, NASA
  source page at 42 seconds, and moving eclipse B-roll at 55 seconds. A separate 99-second
  Live2D window confirms continued pose, mouth, and blink motion. Together they confirm
  complete portrait framing in both layouts, responsive Live2D placement, readable Chinese
  captions, attribution, and closing frame. The frontend reports `已完成` and exposes both
  playback links.
- Final automated verification passes: 281 backend tests, Ruff, mypy over 137 source files,
  32 frontend tests plus lint/typecheck/production build, 33 video tests plus
  typecheck/Remotion bundle, and 10 desktop/mobile Playwright Scene Lab cases using a real
  v1.6 Live2D WebM.
