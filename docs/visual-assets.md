# Script segment visual assets

`visual_hint` remains an editorial instruction for a future image/video
planner. It is never a filesystem path, URL, or media reference. Raster files
use the separate `visual-assets` contract below.

## Binding and revision semantics

An editor upload is bound to exactly one `(story_id, segment_id,
script_revision)` tuple. There is at most one active upload for that tuple.
Replacing it creates a new asset ID, removes the old database binding, and
best-effort removes its old local file after the transaction commits.

The mutation atomically increments the story version. Clients must use the
returned `story_version` for their next write (or reload the story). This
makes a stale editor fail with the normal `concurrent_story_write` response
rather than silently overwriting another editor's image.

Images are editable only while the story is at `SCRIPT_READY` or
`PENDING_SECOND_REVIEW`. They are immutable at the manual-TTS gate, while TTS
is running, after `DONE`, and after archival. Reopen a completed story before
making a final-review visual change.

The internal source-capture seam is separate source evidence, not an editor
mutation; it may register a real capture for any non-archived story when it
holds the current story version.

## HTTP contract

| Operation | Endpoint | Contract |
| --- | --- | --- |
| Read effective current-revision bindings | `GET /api/v1/stories/{story_id}/visual-assets` | Returns `StoryVisualAssets`, including `story_version`, `script_revision`, segment bindings, and an optional captured source screenshot. |
| Replace one segment image | `PUT /api/v1/stories/{story_id}/visual-assets/{segment_id}` | Query: `expected_story_version`, `expected_script_revision`, `filename`. Body: raw `image/png`, `image/jpeg`, or `image/webp` bytes. Returns `VisualAssetMutation`. |
| Remove one segment image | `DELETE /api/v1/stories/{story_id}/visual-assets/{segment_id}` | Query: `expected_story_version`, `expected_script_revision`. Returns `204`; reload the story before the next mutation. |
| Serve asset bytes | `GET /api/v1/stories/{story_id}/visual-assets/{asset_id}/content` | Serves only an asset whose persisted `story_id` matches the route. |

The server accepts PNG, JPEG, and WebP only, limits byte size through
`GOD_NEWS_VISUAL_ASSET_MAX_UPLOAD_BYTES`, structurally parses raster headers,
and rejects images over `GOD_NEWS_VISUAL_ASSET_MAX_PIXELS` before a downstream
renderer can decode them. It derives the storage extension from the verified
content type and never trusts the provided filename for a path. Stored keys
are opaque relative paths below `GOD_NEWS_VISUAL_ASSET_DIR` (or
`output_dir/visual-assets` by default).

## Source-page screenshot behavior

`source_page_url` is only a safe HTTPS browser candidate. It is not a preview
URL and does not imply that a screenshot exists. The UI may display a default
source-page image only when `source_page_screenshot` is non-null.

The current phase has no runtime browser capture worker. A future policy-bound
capture adapter must call `VisualAssetService.register_source_screenshot()`
only after it has captured real raster bytes. That asset has
`origin: source_page_screenshot`, is story-level (not attached to a segment),
and is deliberately distinct from an editor upload.

## Retention and future video rendering

Visual files live under `output_dir`, so existing media retention sees them.
All assets attached to non-archived stories are protected from generic
retention; archive a story to let the normal retention window reclaim its
visual media and historical revisions.

A future renderer must resolve visual media by calling the list endpoint for
the locked story and script revision, then use each returned `asset_id` with
the scoped content endpoint (or an equivalent `VisualAssetStore` adapter). It
must not treat `visual_hint`, a source URL, or a host path as a renderable
asset reference. The content endpoint itself rejects editor-uploaded assets
from old script revisions, even if their retained database row and local file
still exist.
