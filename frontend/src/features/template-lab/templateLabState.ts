import type {EpisodeSceneModule, OutputProfileId} from '@god-news/video/player';

export type TemplateLabTokenPreset = 'default' | 'high_contrast';

export interface TemplateLabState {
  template: string;
  version: string;
  scene: EpisodeSceneModule;
  variant: string;
  profile: OutputProfileId;
  fixture: string;
  frame: number;
  zoom: number;
  safeArea: boolean;
  assetBounds: boolean;
  hostBounds: boolean;
  captionBounds: boolean;
  hostVisible: boolean;
  hostSlot: 'primary' | 'corner';
  hostVideoUrl: string;
  tokenPreset: TemplateLabTokenPreset;
  title: string;
  caption: string;
}

export const DEFAULT_TEMPLATE_LAB_STATE: TemplateLabState = {
  template: 'world_warmth',
  version: '1.0.0',
  scene: 'evidence_fullscreen',
  variant: 'evidence_documentary',
  profile: 'bilibili_horizontal',
  fixture: 'evidence-source-page',
  frame: 0,
  zoom: 0.45,
  safeArea: true,
  assetBounds: false,
  hostBounds: false,
  captionBounds: false,
  hostVisible: false,
  hostSlot: 'primary',
  hostVideoUrl: '/template-lab/host-soyo-30fps.webm',
  tokenPreset: 'default',
  title: '',
  caption: '',
};

const boolParam = (value: string | null, fallback: boolean): boolean => {
  if (value === '1') return true;
  if (value === '0') return false;
  return fallback;
};

const numberParam = (
  value: string | null,
  fallback: number,
  minimum: number,
  maximum: number,
): number => {
  const parsed = value === null ? Number.NaN : Number(value);
  return Number.isFinite(parsed)
    ? Math.min(maximum, Math.max(minimum, parsed))
    : fallback;
};

export const readTemplateLabState = (
  params: URLSearchParams,
): TemplateLabState => {
  const scene = params.get('scene');
  const profile = params.get('profile');
  return {
    template: params.get('template') ?? DEFAULT_TEMPLATE_LAB_STATE.template,
    version: params.get('version') ?? DEFAULT_TEMPLATE_LAB_STATE.version,
    scene:
      scene === 'host_evidence' ||
      scene === 'evidence_fullscreen' ||
      scene === 'source_video'
        ? scene
        : DEFAULT_TEMPLATE_LAB_STATE.scene,
    variant: params.get('variant') ?? DEFAULT_TEMPLATE_LAB_STATE.variant,
    profile:
      profile === 'douyin_vertical' || profile === 'bilibili_horizontal'
        ? profile
        : DEFAULT_TEMPLATE_LAB_STATE.profile,
    fixture: params.get('fixture') ?? DEFAULT_TEMPLATE_LAB_STATE.fixture,
    frame: Math.round(
      numberParam(params.get('frame'), DEFAULT_TEMPLATE_LAB_STATE.frame, 0, 1_000_000),
    ),
    zoom: numberParam(params.get('zoom'), DEFAULT_TEMPLATE_LAB_STATE.zoom, 0.2, 0.8),
    safeArea: boolParam(params.get('safe'), DEFAULT_TEMPLATE_LAB_STATE.safeArea),
    assetBounds: boolParam(params.get('assets'), DEFAULT_TEMPLATE_LAB_STATE.assetBounds),
    hostBounds: boolParam(params.get('hostBounds'), DEFAULT_TEMPLATE_LAB_STATE.hostBounds),
    captionBounds: boolParam(
      params.get('captionBounds'),
      DEFAULT_TEMPLATE_LAB_STATE.captionBounds,
    ),
    hostVisible: boolParam(params.get('host'), DEFAULT_TEMPLATE_LAB_STATE.hostVisible),
    hostSlot: params.get('hostSlot') === 'corner' ? 'corner' : 'primary',
    hostVideoUrl: params.get('hostVideo') ?? '',
    tokenPreset:
      params.get('tokens') === 'high_contrast' ? 'high_contrast' : 'default',
    title: params.get('title') ?? '',
    caption: params.get('caption') ?? '',
  };
};

export const writeTemplateLabState = (
  state: TemplateLabState,
): URLSearchParams => {
  const params = new URLSearchParams({
    template: state.template,
    version: state.version,
    scene: state.scene,
    variant: state.variant,
    profile: state.profile,
    fixture: state.fixture,
    frame: String(state.frame),
    zoom: String(state.zoom),
    safe: state.safeArea ? '1' : '0',
    assets: state.assetBounds ? '1' : '0',
    hostBounds: state.hostBounds ? '1' : '0',
    captionBounds: state.captionBounds ? '1' : '0',
    host: state.hostVisible ? '1' : '0',
    hostSlot: state.hostSlot,
    tokens: state.tokenPreset,
  });
  if (state.hostVideoUrl !== '') params.set('hostVideo', state.hostVideoUrl);
  if (state.title !== '') params.set('title', state.title);
  if (state.caption !== '') params.set('caption', state.caption);
  return params;
};
