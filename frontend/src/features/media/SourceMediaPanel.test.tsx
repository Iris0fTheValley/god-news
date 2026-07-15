import {screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach, describe, expect, it, vi} from 'vitest';

import type {
  ReviewSourceTranscriptionRequest,
  SourceMediaArtifact,
  SourceMediaTranscription,
  Story,
} from '../../api/types';
import {storyFixture} from '../../test/fixtures';
import {renderWithApp} from '../../test/render';
import {SourceMediaPanel} from './SourceMediaPanel';

const apiMocks = vi.hoisted(() => ({
  acquireSourceMedia: vi.fn(),
  cancelSourceMediaTranscription: vi.fn(),
  listSourceMediaArtifacts: vi.fn(),
  listSourceMediaTranscriptions: vi.fn(),
  reviewSourceMediaTranscription: vi.fn(),
  startSourceMediaTranscription: vi.fn(),
}));

vi.mock('../../api/client', () => ({
  acquireSourceMedia: apiMocks.acquireSourceMedia,
  cancelSourceMediaTranscription: apiMocks.cancelSourceMediaTranscription,
  listSourceMediaArtifacts: apiMocks.listSourceMediaArtifacts,
  listSourceMediaTranscriptions: apiMocks.listSourceMediaTranscriptions,
  reviewSourceMediaTranscription: apiMocks.reviewSourceMediaTranscription,
  startSourceMediaTranscription: apiMocks.startSourceMediaTranscription,
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

const pendingTranscription = {
  artifact_id: artifact.artifact_id,
  artifact_sha256: artifact.sha256,
  attempt_count: 1,
  cues: [{
    cue_id: 'f6cb6162-c04c-4c04-87fc-b21166a05070',
    sequence: 0,
    start_ms: 500,
    end_ms: 2600,
    captions: [
      {kind: 'verbatim', language: 'en', text: 'People rebuilt the library.'},
      {kind: 'translation', language: 'zh-CN', text: '人们重建了图书馆。'},
    ],
  }],
  detected_language: 'en',
  language_probability: 0.98,
  failures: [],
  model_identity: 'faster-whisper:1.2.1:base:cpu:int8',
  requested_by: 'story-workbench',
  reviews: [],
  source_language_hint: null,
  status: 'PENDING_REVIEW',
  story_id: videoStory.story_id,
  target_caption_language: 'zh-CN',
  transcription_id: 'c1e789f1-d481-40ce-af8f-0db2027fd113',
  updated_at: '2026-07-15T02:00:00Z',
  version: 3,
} as SourceMediaTranscription;

describe('SourceMediaPanel', () => {
  beforeEach(() => {
    apiMocks.acquireSourceMedia.mockReset();
    apiMocks.cancelSourceMediaTranscription.mockReset();
    apiMocks.listSourceMediaArtifacts.mockReset();
    apiMocks.listSourceMediaTranscriptions.mockReset();
    apiMocks.reviewSourceMediaTranscription.mockReset();
    apiMocks.startSourceMediaTranscription.mockReset();
    apiMocks.listSourceMediaTranscriptions.mockResolvedValue([]);
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

  it('starts local source-video transcription with explicit language policy', async () => {
    const user = userEvent.setup();
    apiMocks.listSourceMediaArtifacts.mockResolvedValue([artifact]);
    apiMocks.startSourceMediaTranscription.mockResolvedValue({
      ...pendingTranscription,
      status: 'QUEUED',
      cues: [],
      detected_language: null,
      language_probability: null,
      version: 1,
    });
    renderWithApp(<SourceMediaPanel story={videoStory} />);

    await user.type(await screen.findByLabelText('原语言提示（可留空自动检测）'), 'en');
    await user.click(screen.getByRole('button', {name: '生成原视频字幕'}));

    await waitFor(() => expect(apiMocks.startSourceMediaTranscription).toHaveBeenCalledWith(
      videoStory.story_id,
      artifact.artifact_id,
      {
        expected_story_version: videoStory.version,
        requested_by: 'story-workbench',
        source_language_hint: 'en',
        target_caption_language: videoStory.target_language,
      },
    ));
  });

  it('edits translated captions while preserving ASR timing evidence', async () => {
    const user = userEvent.setup();
    apiMocks.listSourceMediaArtifacts.mockResolvedValue([artifact]);
    apiMocks.listSourceMediaTranscriptions.mockResolvedValue([pendingTranscription]);
    apiMocks.reviewSourceMediaTranscription.mockResolvedValue({
      ...pendingTranscription,
      status: 'APPROVED',
      version: 4,
    });
    renderWithApp(<SourceMediaPanel story={videoStory} />);

    const translation = await screen.findByLabelText('翻译 · zh-CN');
    await user.clear(translation);
    await user.type(translation, '大家一起重建了图书馆。');
    await user.click(screen.getByRole('button', {name: '批准字幕'}));

    await waitFor(() => expect(apiMocks.reviewSourceMediaTranscription).toHaveBeenCalledOnce());
    const call = apiMocks.reviewSourceMediaTranscription.mock.calls.at(-1) as unknown as [
      string,
      string,
      string,
      ReviewSourceTranscriptionRequest,
    ];
    expect(call.slice(0, 3)).toEqual([
      videoStory.story_id,
      artifact.artifact_id,
      pendingTranscription.transcription_id,
    ]);
    expect(call[3].decision).toBe('approve');
    expect(call[3].expected_version).toBe(pendingTranscription.version);
    expect(call[3].revised_cues?.[0]?.start_ms).toBe(500);
    expect(call[3].revised_cues?.[0]?.end_ms).toBe(2600);
    expect(call[3].revised_cues?.[0]?.captions).toContainEqual(
      expect.objectContaining({text: '大家一起重建了图书馆。'}),
    );
  });
});
