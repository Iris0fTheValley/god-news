# god-news design system

**Product:** a single-operator good-news broadcast rundown and review desk
**Primary job:** let the editor understand evidence, state, and the next safe action without losing context
**Density / motion / variance:** 8 / 3 / 6

## Direction: broadcast rundown, not generic admin cards

The interface borrows from television rundown sheets: every story is a cue with a source stamp,
category band, duration, state, and one next action. A continuous vertical **cue rail** is the
signature element. It appears in the queue and detail view, maps exactly to the seven FSM states,
and never becomes decorative progress chrome.

Avoid magazine hero layouts, glass panels, neon gradients, KPI-card walls, and pink-on-navy
entertainment dashboards. This is a calm production instrument for one editor.

## Tokens

### Color

| Role | Light | Dark | Use |
|---|---|---|---|
| background | `#E8EFEC` | `#101A17` | mineral desk surface |
| surface | `#F8FAF8` | `#17231F` | working panels |
| elevated | `#FFFFFF` | `#1D2C27` | inspector and dialogs |
| ink | `#14231D` | `#F2F7F4` | primary text |
| muted ink | `#596A63` | `#A9B8B1` | metadata |
| rule | `#B9C9C2` | `#34463F` | dividers and fields |
| primary | `#176B57` | `#5BC3A3` | approve / active cue |
| signal | `#D98513` | `#F5B84B` | pending review |
| timeline | `#356FA8` | `#75A9DE` | audio and timing |
| danger | `#B84E42` | `#EF8C80` | failures / destructive |
| focus | `#7756C7` | `#B79DFF` | keyboard focus only |

Status must always pair color with its exact text label. Category colors are narrow edge bands,
never full-card fills.

### Type

- Display and navigation: `"Bricolage Grotesque", "Segoe UI Variable", sans-serif`
- Body and multilingual content: `"Noto Sans SC", "Microsoft YaHei UI", "Segoe UI", sans-serif`
- IDs, durations, hashes, state and trace data: `"IBM Plex Mono", "Cascadia Mono", monospace`
- Base size 16px; metadata no smaller than 12px; body line-height 1.55.
- Use tabular figures for duration, counts, timestamps, and versions.

Fonts must be bundled by the frontend or fall back locally; core operation cannot depend on Google
Fonts being reachable.

### Spacing and shape

- 4px base rhythm: `4 / 8 / 12 / 16 / 24 / 32 / 48`.
- Controls are at least 44px high; icon-only controls still have a 44px hit target and label.
- Working panels use 8px radius; cues use 0–4px radius and visible rules, not floating shadows.
- Shadows are reserved for dialogs and the mobile inspector sheet.

## Layout

Desktop (≥1180px):

```text
┌──────────────┬─────────────────────────────────┬────────────────────────┐
│ sources/nav  │ cue queue / script / timeline   │ evidence + next action │
│ 216px        │ fluid                           │ 400–460px               │
└──────────────┴─────────────────────────────────┴────────────────────────┘
```

Tablet: navigation collapses to a labeled top rail; inspector becomes an inline region.
Mobile: one column; filter sheet and inspector use native dialog semantics. No horizontal scroll.

The queue preserves filter and scroll state when opening a story. Every main screen has a deep URL.

## Component rules

### Cue row

- 4px category band → source stamp → title/summary → state → age/duration → next action.
- Entire row may open detail, but nested buttons remain separate keyboard targets.
- Failures show the stable error code plus a concrete retry path.
- Used stories remain searchable but are visually stamped `USED` and excluded from candidate views.

### Seven-state cue rail

- Render the exact FSM labels in order; current, complete, and future states have shape and text
  differences in addition to color.
- A failed operation annotates its owning state; it never invents an eighth state.
- Transition history is accessible as a table, not only as a graphic.

### Review editor

- Evidence, editable fields, and approve/request-changes controls stay visible in the same view.
- Approve is the one primary action. Request changes is secondary, never styled as destructive.
- Show the story version being reviewed; stale versions explain reload-and-retry inline.
- Long edits autosave locally; warn before dismissing unsaved work.

### Script and timeline

- Segment blocks are separated by speaker identity even in single-host mode.
- Audio playback, exact duration, and transcript remain aligned by `segment_id`.
- Timeline editing uses labeled numeric fields and ordering controls, not pixel dragging.

## Motion and feedback

- 160–220ms opacity/translate transitions only; no GSAP dependency for core screens.
- Loading beyond 300ms uses a skeleton matching final geometry.
- Buttons show pending state and cannot double-submit.
- Toasts use `aria-live="polite"`; validation errors sit beside the field and focus the first error.
- Respect `prefers-reduced-motion`; all state remains understandable with motion disabled.

## Accessibility and verification

- WCAG AA contrast (4.5:1 body text), visible 3px focus ring, semantic landmarks and headings.
- Full workflow operable by keyboard; no action depends on hover, color, or drag.
- Test at 375, 768, 1024, and 1440px; test 200% zoom and reduced motion.
- Use one SVG icon family (Lucide), never emoji as structural icons.
- Browser acceptance must cover: filter queue → open story → initial review → audio playback → final
  review, including a stale-version and a recoverable failure path.
