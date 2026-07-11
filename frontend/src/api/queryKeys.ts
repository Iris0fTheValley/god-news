export const queryKeys = {
  stories: (status?: string) => ['stories', status ?? 'all'] as const,
  story: (storyId: string) => ['story', storyId] as const,
  reviews: (storyId: string) => ['story', storyId, 'reviews'] as const,
  transitions: (storyId: string) => ['story', storyId, 'transitions'] as const,
  manifest: (storyId: string) => ['story', storyId, 'manifest'] as const,
  classificationMetrics: () => ['metrics', 'classification'] as const,
};
