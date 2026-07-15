import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {SourceMediaArtifact, Story} from '../../api/types';
import {storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {SourceMediaPanel} from './SourceMediaPanel';

const apiMocks = vi.hoisted(() => ({
  acquireSourceMedia: vi.fn(),
  listSourceMediaArtifacts: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  acquireSourceMedia: apiMocks.acquireSourceMedia,
  listSourceMediaArtifacts: apiMocks.listSourceMediaArtifacts,
  sourceMediaContentUrl: (storyId: string, artifactId: string) => (
    `/api/v1/stories/${storyId}/source-media/${artifactId}/content`
  ),
}));

const videoStory = {
  ...storyFixture,
  provenance: {
    schema_version: '1.0',
    source: 'reddit',
    external_id: 'reddit-1',
    canonical_url: 'https://www.reddit.com/r/goodnews/comments/reddit-1/story',
    title: 'A good story',
    content_text: 'A community helped a family.',
    content_sha256: 'b'.repeat(64),
    language: 'en',
    author: 'kind-user',
    published_at: '2026-07-15T00:00:00Z',
    media: [{
      kind: 'video',
      url: 'https://v.redd.it/reddit-1/DASH_720.mp4?source=fallback',
      poster_url: null,
      caption: null,
      credit: null,
      duration_ms: 18_000,
    }],
    attribution: {
      source: 'reddit',
      publisher: 'Reddit / r/goodnews',
      original_url: 'https://www.reddit.com/r/goodnews/comments/reddit-1/story',
      author: 'kind-user',
      attribution_text: 'Posted by u/kind-user on Reddit',
    },
    rights: {
      status: 'unknown',
      copyright_holder: null,
      license_name: null,
      license_url: null,
      terms_url: 'https://www.redditinc.com/policies/user-agreement',
      allows_republication: null,
      allows_derivatives: null,
      requires_attribution: true,
      requires_human_review: true,
    },
    flags: {
      is_user_generated: true,
      is_nsfw: false,
      is_spoiler: false,
      has_images: false,
      has_video: true,
      has_audio: false,
      requires_rights_review: true,
    },
    source_fields: {
      source: 'reddit',
      post_id: 'reddit-1',
      subreddit: 'goodnews',
      score: 42,
      num_comments: 3,
      flair: null,
      locked: false,
      is_self: false,
      outbound_url: null,
    },
  },
} as Story;

const artifact = {
  artifact_id: '5cb5b8c7-2dd5-4e39-9804-53ea9d68d412',
  story_id: videoStory.story_id,
  source: 'reddit',
  media_index: 0,
  acquired_by: 'story-workbench',
  source_url: videoStory.provenance?.media?.[0]?.url ?? '',
  canonical_story_url: videoStory.provenance?.canonical_url ?? '',
  attribution: videoStory.provenance?.attribution,
  rights: videoStory.provenance?.rights,
  publish_eligible: false,
  content_type: 'video/mp4',
  filename: 'source-0.mp4',
  sha256: 'c'.repeat(64),
  size_bytes: 4_194_304,
  probe: {
    duration_ms: 18_000,
    width: 720,
    height: 1_280,
    video_codec: 'h264',
    audio_codec: 'aac',
    fps: 30,
  },
  retrieved_at: '2026-07-15T01:00:00Z',
} as SourceMediaArtifact;

describe('SourceMediaPanel', () => {
  beforeEach(() => {
    apiMocks.acquireSourceMedia.mockReset();
    apiMocks.listSourceMediaArtifacts.mockReset();
  });

  it('acquires a selected source video against the current story version', async () => {
    const user = userEvent.setup();
    apiMocks.listSourceMediaArtifacts.mockResolvedValue([]);
    apiMocks.acquireSourceMedia.mockResolvedValue(artifact);
    renderWithApp(<SourceMediaPanel story={videoStory} />);

    await user.click(await screen.findByRole('button', {name: '采集供审核'}));

    await waitFor(() => expect(apiMocks.acquireSourceMedia).toHaveBeenCalledWith(
      videoStory.story_id,
      {
        expected_story_version: videoStory.version,
        media_index: 0,
        requested_by: 'story-workbench',
      },
    ));
  });

  it('shows immutable evidence without exposing a host storage path', async () => {
    apiMocks.listSourceMediaArtifacts.mockResolvedValue([artifact]);
    renderWithApp(<SourceMediaPanel story={videoStory} />);

    expect(await screen.findByText('仅供审核，权利待确认')).toBeVisible();
    expect(screen.getByText(/SHA-256 cccccccccccc/)).toBeVisible();
    const video = document.querySelector('video');
    expect(video).not.toBeNull();
    expect(video?.getAttribute('src')).toBe(
      `/api/v1/stories/${videoStory.story_id}/source-media/${artifact.artifact_id}/content`,
    );
    expect(document.body.textContent).not.toContain('I:\\');
    expect(document.body.textContent).not.toContain('storage_key');
  });
});
