import createClient from 'openapi-fetch';

import type {paths} from './generated';
import type {
  BgmTrack,
  CreateVideoBatch,
  FirstReviewSubmission,
  IngestRequest,
  OperationRun,
  ProblemDetail,
  RenderVideoBatch,
  RetentionCleanupCommand,
  RoleProfileCreate,
  RoleProfileReplace,
  ScheduleSnapshot,
  SecondReviewSubmission,
  SourceRunRequest,
  SourceRunStatus,
  StoryStatus,
  StoryUpdate,
  SubmitTimelineReview,
  VideoBatchStatus,
} from './types';

export interface SourceRunListParams {
  source?: SourceRunRequest['source'] | null;
  run_status?: SourceRunStatus | null;
  limit?: number;
  offset?: number;
}

export interface VideoBatchListParams {
  status?: VideoBatchStatus | null;
  limit?: number;
  offset?: number;
}

const api = createClient<paths>({baseUrl: ''});

export class ApiProblem extends Error {
  readonly code: string;
  readonly status: number;
  readonly storyId: string | null;

  constructor(problem: ProblemDetail, status: number) {
    super(problem.message);
    this.name = 'ApiProblem';
    this.code = problem.code;
    this.status = status;
    this.storyId = problem.story_id ?? null;
  }
}

function throwProblem(error: unknown, response: Response): never {
  const fallback: ProblemDetail = {
    code: 'unexpected_response',
    message: `服务返回了无法识别的错误（HTTP ${String(response.status)}）。`,
    trace_id: response.headers.get('X-Trace-ID') ?? 'unknown',
    story_id: null,
  };
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
    throw new ApiProblem(error as ProblemDetail, response.status);
  }
  throw new ApiProblem(fallback, response.status);
}

export async function listStories(status?: StoryStatus) {
  const result = await api.GET('/api/v1/stories', {
    params: {query: {status, limit: 50, offset: 0}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getStory(storyId: string) {
  const result = await api.GET('/api/v1/stories/{story_id}', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function createStory(body: IngestRequest) {
  const result = await api.POST('/api/v1/stories', {body});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function submitFirstReview(storyId: string, body: FirstReviewSubmission) {
  const result = await api.POST('/api/v1/stories/{story_id}/reviews/first', {
    params: {path: {story_id: storyId}},
    body,
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function submitSecondReview(storyId: string, body: SecondReviewSubmission) {
  const result = await api.POST('/api/v1/stories/{story_id}/reviews/second', {
    params: {path: {story_id: storyId}},
    body,
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function resumeStory(storyId: string) {
  const result = await api.POST('/api/v1/stories/{story_id}/resume', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function listReviews(storyId: string) {
  const result = await api.GET('/api/v1/stories/{story_id}/reviews', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function listTransitions(storyId: string) {
  const result = await api.GET('/api/v1/stories/{story_id}/transitions', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getProductionManifest(storyId: string) {
  const result = await api.GET('/api/v1/stories/{story_id}/production-manifest', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getClassificationMetrics() {
  const result = await api.GET('/api/v1/metrics/classification');
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getSourceHealth(probeNetwork = false) {
  const result = await api.GET('/api/v1/sources/health', {
    params: {query: {probe_network: probeNetwork}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export function audioClipUrl(storyId: string, segmentId: string): string {
  return `/api/v1/stories/${encodeURIComponent(storyId)}/audio/${encodeURIComponent(segmentId)}`;
}

/* ── Roles ── */

export async function listRoles(enabled?: boolean | null) {
  const result = await api.GET('/api/v1/roles', {
    params: {query: {enabled}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getRole(profileId: string) {
  const result = await api.GET('/api/v1/roles/{profile_id}', {
    params: {path: {profile_id: profileId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function createRole(body: RoleProfileCreate) {
  const result = await api.POST('/api/v1/roles', {body});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function updateRole(profileId: string, body: RoleProfileReplace) {
  const result = await api.PUT('/api/v1/roles/{profile_id}', {
    params: {path: {profile_id: profileId}},
    body,
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function deleteRole(profileId: string, expectedVersion: number) {
  const result = await api.DELETE('/api/v1/roles/{profile_id}', {
    params: {path: {profile_id: profileId}},
    body: {expected_version: expectedVersion},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

/* ── Source Runs ── */

export async function getSourceCollectors() {
  const result = await api.GET('/api/v1/sources/collectors');
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function startSourceRun(body: SourceRunRequest) {
  const result = await api.POST('/api/v1/source-runs', {body});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function listSourceRuns(params?: SourceRunListParams) {
  const result = await api.GET('/api/v1/source-runs', {params: {query: params}});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getSourceRun(runId: string) {
  const result = await api.GET('/api/v1/source-runs/{run_id}', {
    params: {path: {run_id: runId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

/* ── Video ── */

export async function listBgmTracks(): Promise<BgmTrack[]> {
  const result = await api.GET('/api/v1/video/bgm');
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function createVideoBatch(body: CreateVideoBatch) {
  const result = await api.POST('/api/v1/video/batches', {body});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function listVideoBatches(params?: VideoBatchListParams) {
  const result = await api.GET('/api/v1/video/batches', {params: {query: params}});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function getVideoBatch(batchId: string) {
  const result = await api.GET('/api/v1/video/batches/{batch_id}', {
    params: {path: {batch_id: batchId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function submitTimelineReview(batchId: string, body: SubmitTimelineReview) {
  const result = await api.POST('/api/v1/video/batches/{batch_id}/timeline-review', {
    params: {path: {batch_id: batchId}},
    body,
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function renderVideoBatch(batchId: string, body: RenderVideoBatch) {
  const result = await api.POST('/api/v1/video/batches/{batch_id}/render', {
    params: {path: {batch_id: batchId}},
    body,
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

/* ── Operations ── */

export async function triggerRetention(body: RetentionCleanupCommand) {
  const result = await api.POST('/api/v1/operations/retention/runs', {body});
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function listOperationRuns(): Promise<OperationRun[]> {
  const result = await api.GET('/api/v1/operations/runs');
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function listSchedules(): Promise<ScheduleSnapshot[]> {
  const result = await api.GET('/api/v1/operations/schedules');
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

/* ── Story lifecycle additions ── */

/** DELETE /api/v1/stories/{story_id} — implemented by the archive lifecycle route. */
export async function deleteStory(storyId: string) {
  const result = await api.DELETE('/api/v1/stories/{story_id}', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

/** POST /api/v1/stories/{story_id}/reopen — implemented by the lifecycle route. */
export async function reopenStory(storyId: string) {
  const result = await api.POST('/api/v1/stories/{story_id}/reopen', {
    params: {path: {story_id: storyId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function cancelSourceRun(runId: string) {
  const result = await api.POST('/api/v1/source-runs/{run_id}/cancel', {
    params: {path: {run_id: runId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function cancelVideoRender(batchId: string) {
  const result = await api.POST('/api/v1/video/batches/{batch_id}/cancel', {
    params: {path: {batch_id: batchId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}

export async function deleteVideoBatch(batchId: string): Promise<void> {
  const result = await api.DELETE('/api/v1/video/batches/{batch_id}', {
    params: {path: {batch_id: batchId}},
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
}

/** PATCH /api/v1/stories/{story_id} — requires the current story version. */
export async function updateStory(storyId: string, body: StoryUpdate) {
  const result = await api.PATCH('/api/v1/stories/{story_id}', {
    params: {path: {story_id: storyId}},
    body,
  });
  if (result.error !== undefined) throwProblem(result.error, result.response);
  return result.data;
}
