import createClient from 'openapi-fetch';

import type {paths} from './generated';
import type {
  FirstReviewSubmission,
  IngestRequest,
  ProblemDetail,
  SecondReviewSubmission,
  StoryStatus,
} from './types';

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

export function audioClipUrl(storyId: string, segmentId: string): string {
  return `/api/v1/stories/${encodeURIComponent(storyId)}/audio/${encodeURIComponent(segmentId)}`;
}
