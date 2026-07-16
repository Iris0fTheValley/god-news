import {
  parseGodNewsVideoProps,
  type EpisodeSceneModule,
  type GodNewsVideoProps,
  type OutputProfileId,
  type TemplateDefinition,
  type VisualAssetType,
} from '../schema';
import {worldWarmthTemplate} from '../templates/world-warmth';

const BATCH_ID = 'af8ee365-b88c-4dfc-8fbd-a75b67cf35f0';
const SEGMENT_ID = '6901405c-0b2d-4089-b273-136f375ee84c';
const SCENE_ID = 'b0e8f596-8e70-4c34-a5d5-0eb2dd6eb26c';
const IMAGE_ASSET_ID = '68da94dd-2c4f-4cd8-a7f2-75a23df4c7aa';
const SCREENSHOT_ASSET_ID = '33e4ce23-5e28-43bf-a76f-b96bffbc7498';
const SOURCE_VIDEO_ASSET_ID = 'c7c3e628-1bc3-4b72-ad7c-acde4ed91e12';
const TRANSCRIPTION_ID = '518d34f9-b5e2-4897-a2eb-4e2679c76366';
const CUE_ID = '6092d5e5-a19a-4f30-a48e-b0c0fa9c78a3';
const HOST_ASSET_ID = '83d29148-009e-47aa-a75f-f0f9056c3cad';
const ROLE_PROFILE_ID = 'dbf05d6a-720d-4e58-a92f-e2c158854b04';
const SHA_A = 'a'.repeat(64);
const SHA_B = 'b'.repeat(64);
const SHA_C = 'c'.repeat(64);
const SHA_LOW_RES =
  'ec02cf09cabfb33c4356f42679f49abad1fd8c85ebca7e8399ebc103b55df051';

export interface TemplateLabFixtureDefinition {
  fixtureId: string;
  displayName: string;
  moduleId: EpisodeSceneModule;
  variantId: string;
  title: string;
  spokenText: string;
  translatedCaption: string;
  assetId: string;
  assetType: VisualAssetType;
  assetUrl: string;
  sourceLabel: string;
  sourceUrl: string;
  width: number;
  height: number;
}

export const TEMPLATE_LAB_FIXTURES = Object.freeze([
  {
    fixtureId: 'host-volunteers',
    displayName: '主持人 + 志愿者横图',
    moduleId: 'host_evidence',
    variantId: 'host_split_editorial',
    title: '志愿者让社区图书馆重新亮起来',
    spokenText:
      'Volunteers reopened a community library and returned a quiet meeting place to the neighborhood.',
    translatedCaption: '志愿者重新开放社区图书馆，也把安静的相聚空间还给了邻里。',
    assetId: IMAGE_ASSET_ID,
    assetType: 'image',
    assetUrl: '/template-lab/library-volunteers.png',
    sourceLabel: 'GOD NEWS 自制演示素材',
    sourceUrl: 'https://example.invalid/god-news/library-volunteers',
    width: 1672,
    height: 941,
  },
  {
    fixtureId: 'host-corner-volunteers',
    displayName: '角落主持人 + 全幅横图',
    moduleId: 'host_evidence',
    variantId: 'host_corner_full_bleed',
    title: '一座图书馆，一群愿意伸手的人',
    spokenText:
      'A small group of volunteers repaired the shelves, sorted the books, and welcomed readers back.',
    translatedCaption: '一群志愿者修好书架、整理图书，重新欢迎读者回到这里。',
    assetId: IMAGE_ASSET_ID,
    assetType: 'image',
    assetUrl: '/template-lab/library-volunteers.png',
    sourceLabel: 'GOD NEWS 自制演示素材',
    sourceUrl: 'https://example.invalid/god-news/library-volunteers',
    width: 1672,
    height: 941,
  },
  {
    fixtureId: 'host-short-title',
    displayName: '极短标题 + 主持人',
    moduleId: 'host_evidence',
    variantId: 'host_split_editorial',
    title: '重开',
    spokenText: 'The reading room is open again.',
    translatedCaption: '社区阅读室重新开放。',
    assetId: IMAGE_ASSET_ID,
    assetType: 'image',
    assetUrl: '/template-lab/library-volunteers.png',
    sourceLabel: 'GOD NEWS 自制演示素材',
    sourceUrl: 'https://example.invalid/god-news/library-volunteers',
    width: 1672,
    height: 941,
  },
  {
    fixtureId: 'host-long-title',
    displayName: '极长标题 + 角落主持人',
    moduleId: 'host_evidence',
    variantId: 'host_corner_full_bleed',
    title:
      '志愿者连续数周整理捐赠书籍并修复社区阅读空间，让邻里重新拥有安静相聚的公共场所',
    spokenText:
      'Volunteers spent several weeks repairing a shared reading room and sorting every donated book.',
    translatedCaption:
      '志愿者连续数周修复阅读空间、整理捐赠书籍，让邻里重新拥有公共阅读场所。',
    assetId: IMAGE_ASSET_ID,
    assetType: 'image',
    assetUrl: '/template-lab/library-volunteers.png',
    sourceLabel: 'GOD NEWS 自制演示素材',
    sourceUrl: 'https://example.invalid/god-news/library-volunteers',
    width: 1672,
    height: 941,
  },
  {
    fixtureId: 'evidence-source-page',
    displayName: '来源网页截图',
    moduleId: 'evidence_fullscreen',
    variantId: 'evidence_documentary',
    title: '来源证据：社区图书馆重新开放',
    spokenText:
      'The source page records the reopening date, the volunteer effort, and the public access details.',
    translatedCaption: '来源页面记录了重新开放日期、志愿行动和公众开放信息。',
    assetId: SCREENSHOT_ASSET_ID,
    assetType: 'source_screenshot',
    assetUrl: '/template-lab/community-library-source.png',
    sourceLabel: 'GOD NEWS 自制来源页',
    sourceUrl: 'https://example.invalid/god-news/community-library',
    width: 1280,
    height: 1649,
  },
  {
    fixtureId: 'evidence-long-caption',
    displayName: '超长双语字幕压力测试',
    moduleId: 'evidence_fullscreen',
    variantId: 'evidence_documentary',
    title: '当社区共同维护一处公共空间，善意便有了可以持续发生的地方',
    spokenText:
      'When neighbors protect a shared public space, small acts of kindness gain a place where they can continue.',
    translatedCaption:
      '当邻里共同保护一处可自由进入的公共空间，那些看似微小的善意就不再只是偶然，而会在阅读、相遇和互相帮助中继续发生。',
    assetId: SCREENSHOT_ASSET_ID,
    assetType: 'source_screenshot',
    assetUrl: '/template-lab/community-library-source.png',
    sourceLabel: 'GOD NEWS 自制来源页',
    sourceUrl: 'https://example.invalid/god-news/community-library',
    width: 1280,
    height: 1649,
  },
  {
    fixtureId: 'evidence-horizontal-image',
    displayName: '无主持人 + 单张横图',
    moduleId: 'evidence_fullscreen',
    variantId: 'evidence_documentary',
    title: '横图证据适配',
    spokenText: 'The reviewed horizontal image fills the evidence region.',
    translatedCaption: '已审核横图按当前比例进入证据区域。',
    assetId: IMAGE_ASSET_ID,
    assetType: 'image',
    assetUrl: '/template-lab/library-volunteers.png',
    sourceLabel: 'GOD NEWS 自制演示素材',
    sourceUrl: 'https://example.invalid/god-news/library-volunteers',
    width: 1672,
    height: 941,
  },
  {
    fixtureId: 'evidence-vertical-image',
    displayName: '无主持人 + 单张竖图',
    moduleId: 'evidence_fullscreen',
    variantId: 'evidence_documentary',
    title: '竖图证据适配',
    spokenText: 'The reviewed portrait source page remains legible.',
    translatedCaption: '已审核竖向来源页保持可读且不越过安全区。',
    assetId: SCREENSHOT_ASSET_ID,
    assetType: 'source_screenshot',
    assetUrl: '/template-lab/community-library-source.png',
    sourceLabel: 'GOD NEWS 自制来源页',
    sourceUrl: 'https://example.invalid/god-news/community-library',
    width: 1280,
    height: 1649,
  },
  {
    fixtureId: 'evidence-low-resolution',
    displayName: '低分辨率素材压力测试',
    moduleId: 'evidence_fullscreen',
    variantId: 'evidence_documentary',
    title: '320×180 素材降级展示',
    spokenText: 'A deliberately low-resolution approved asset tests the media frame.',
    translatedCaption: '经明确标记的低分辨率素材用于检查媒体框降级表现。',
    assetId: IMAGE_ASSET_ID,
    assetType: 'image',
    assetUrl: '/template-lab/library-volunteers-low-res.png',
    sourceLabel: 'GOD NEWS 自制低分辨率测试派生素材',
    sourceUrl: 'https://example.invalid/god-news/library-volunteers-low-res',
    width: 320,
    height: 180,
  },
  {
    fixtureId: 'source-video-owned',
    displayName: '项目自有有限源视频',
    moduleId: 'source_video',
    variantId: 'source_video_clean',
    title: '有限长度原始视频与双语字幕',
    spokenText: 'A finite project-owned documentary clip follows the reviewed story.',
    translatedCaption: '项目自有的有限长度视频片段跟随已审核故事播放。',
    assetId: SOURCE_VIDEO_ASSET_ID,
    assetType: 'source_video',
    assetUrl: '/template-lab/project-owned-source.mp4',
    sourceLabel: 'GOD NEWS 项目自有有限视频',
    sourceUrl: 'https://example.invalid/god-news/project-owned-source',
    width: 1280,
    height: 720,
  },
] satisfies readonly TemplateLabFixtureDefinition[]);

export interface TemplateLabFixtureOptions {
  fixtureId: string;
  profileId: OutputProfileId;
  variantId?: string;
  title?: string;
  translatedCaption?: string;
  hostVisible?: boolean;
  hostSlot?: 'primary' | 'corner';
  hostVideoUrl?: string;
  tokenPreset?: 'default' | 'high_contrast';
}

export interface TemplateLabFixtureResult {
  props: GodNewsVideoProps | null;
  available: boolean;
  diagnostics: readonly string[];
  fixture: TemplateLabFixtureDefinition | null;
}

const withTokenPreset = (
  preset: TemplateLabFixtureOptions['tokenPreset'],
): TemplateDefinition => {
  if (preset !== 'high_contrast') return worldWarmthTemplate;
  return {
    ...worldWarmthTemplate,
    design_tokens: {
      ...worldWarmthTemplate.design_tokens,
      background: '#050706',
      foreground: '#ffffff',
      accent: '#9adcae',
      signal: '#ffd166',
      panel: '#101713',
      muted: '#d9e6dd',
      border_width: 3,
    },
  };
};

export const createTemplateLabFixture = (
  options: TemplateLabFixtureOptions,
): TemplateLabFixtureResult => {
  const fixture =
    TEMPLATE_LAB_FIXTURES.find((candidate) => candidate.fixtureId === options.fixtureId) ??
    null;
  if (!fixture) {
    return {
      props: null,
      available: false,
      diagnostics: [`未知 fixture：${options.fixtureId}`],
      fixture: null,
    };
  }

  const requestedHostVisible = options.hostVisible ?? fixture.moduleId === 'host_evidence';
  const moduleId: EpisodeSceneModule =
    fixture.moduleId === 'host_evidence' && !requestedHostVisible
      ? 'evidence_fullscreen'
      : fixture.moduleId;
  const template = withTokenPreset(options.tokenPreset);
  const variantId =
    moduleId === fixture.moduleId
      ? (options.variantId ?? fixture.variantId)
      : template.default_scene_variants[moduleId];
  if (!variantId) {
    return {
      props: null,
      available: false,
      diagnostics: [`模板没有为 ${moduleId} 注册默认变体。`],
      fixture,
    };
  }

  const hostVisible = moduleId === 'host_evidence';
  const hostSlot =
    hostVisible
      ? variantId === 'host_corner_full_bleed'
        ? 'corner'
        : (options.hostSlot ?? 'primary')
      : null;
  const diagnostics: string[] = [];
  let fatalDiagnostic = false;
  if (hostVisible && !options.hostVideoUrl) {
    diagnostics.push('当前主持人 fixture 缺少真实 Live2D 预渲染 URL，预览已停止。');
    fatalDiagnostic = true;
  }
  const fallbackScreenshot = {
    asset_id: SCREENSHOT_ASSET_ID,
    story_id: BATCH_ID,
    segment_id: null,
    asset_type: 'source_screenshot',
    content_type: 'image/png',
    filename: 'community-library-source.png',
    local_path: '/template-lab/community-library-source.png',
    sha256: SHA_A,
    size_bytes: 1,
    width: 1280,
    height: 1649,
    source_label: 'GOD NEWS 自制来源页',
    source_url: 'https://example.invalid/god-news/community-library',
  } as const;
  const asset = {
    asset_id: fixture.assetId,
    story_id: BATCH_ID,
    segment_id: fixture.assetType === 'image' ? SEGMENT_ID : null,
    asset_type: fixture.assetType,
    content_type: 'image/png',
    filename: fixture.assetUrl.split('/').at(-1) ?? 'template-lab-asset.png',
    local_path: fixture.assetUrl,
    sha256:
      fixture.fixtureId === 'evidence-low-resolution' ? SHA_LOW_RES : SHA_A,
    size_bytes: 1,
    width: fixture.width,
    height: fixture.height,
    source_label: fixture.sourceLabel,
    source_url: fixture.sourceUrl,
  } as const;
  const caption = options.translatedCaption ?? fixture.translatedCaption;
  const captionWarningLength =
    options.profileId === 'douyin_vertical' ? 42 : 64;
  if (caption.length > captionWarningLength) {
    diagnostics.push(
      `中文字幕超过当前比例建议的 ${captionWarningLength} 个字符，请检查双行截断和安全区。`,
    );
  }
  const hostVideoUrl = options.hostVideoUrl?.trim();
  const sourceVideo: GodNewsVideoProps['source_videos'][number] = {
    asset_id: SOURCE_VIDEO_ASSET_ID,
    story_id: BATCH_ID,
    transcription_id: TRANSCRIPTION_ID,
    transcription_version: 2,
    transcription_review: {
      reviewer_id: 'template-lab-reviewer',
      decision: 'approve',
      reviewed_version: 1,
      reviewed_at: '2026-07-16T00:00:00Z',
    },
    local_path: fixture.assetUrl,
    sha256: SHA_C,
    size_bytes: 1,
    duration_ms: 6000,
    width: fixture.width,
    height: fixture.height,
    in_ms: 0,
    out_ms: 6000,
    audio_mode: 'original',
    source_label: fixture.sourceLabel,
    captions: [
      {
        cue_id: CUE_ID,
        sequence: 0,
        start_ms: 0,
        end_ms: 6000,
        captions: [
          {language: 'en-US', kind: 'verbatim', text: fixture.spokenText},
          {language: 'zh-CN', kind: 'translation', text: caption},
        ],
      },
    ],
  };
  const isSourceVideo = moduleId === 'source_video';

  const raw: GodNewsVideoProps = {
    manifest: {
      schema_version: '2.0',
      story_id: BATCH_ID,
      script_revision: 1,
      spoken_language: 'en-US',
      total_duration_ms: isSourceVideo ? 1000 : 6000,
      timeline: [
        {
          segment_id: SEGMENT_ID,
          sequence: 0,
          start_ms: 0,
          end_ms: isSourceVideo ? 1000 : 6000,
          spoken_text: fixture.spokenText,
          spoken_language: 'en-US',
          captions: [
            {language: 'en-US', kind: 'verbatim', text: fixture.spokenText},
            {language: 'zh-CN', kind: 'translation', text: caption},
          ],
          speaker_id: 'template-lab-host',
          emotion: 'happiness',
          scene_transition: 'crossfade',
          visual_hint: null,
          audio_path:
            'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=',
        },
      ],
    },
    title: options.title?.trim() || fixture.title,
    subtitle: 'TEMPLATE LAB · VERIFIED PRODUCTION COMPONENT',
    intro_duration_ms: 0,
    outro_duration_ms: 0,
    transition_duration_ms: 0,
    theme: {
      background: template.design_tokens.background,
      foreground: template.design_tokens.foreground,
      accent: template.design_tokens.accent,
      signal: template.design_tokens.signal,
    },
    visual_reservations:
      hostVisible && hostVideoUrl
        ? {
            renderer: 'live2d_prerender',
            host_videos: [
              {
                asset_id: HOST_ASSET_ID,
                segment_id: SEGMENT_ID,
                speaker_id: 'template-lab-host',
                role_profile_id: ROLE_PROFILE_ID,
                role_profile_version: 1,
                model_sha256: SHA_B,
                audio_sha256: SHA_C,
                local_path: hostVideoUrl,
                sha256: SHA_A,
                size_bytes: 1,
                duration_ms: 6000,
                width: 720,
                height: 720,
                fps: 30,
                video_codec: 'vp9',
              },
            ],
          }
        : {renderer: 'placeholder', host_videos: []},
    episode_plan: {
      schema_version: '1.0',
      batch_id: BATCH_ID,
      scenes: isSourceVideo
        ? [
            {
              scene_id: SCENE_ID,
              sequence: 0,
              module_id: 'evidence_fullscreen',
              narration_segment_id: SEGMENT_ID,
              source_video_asset_id: null,
              speaker_id: 'template-lab-host',
              host_visibility: 'hidden',
              host_slot: null,
              host_enter: false,
              host_exit: false,
              transition_type: 'crossfade',
              variant_id: 'evidence_documentary',
              visual_asset_ids: [SCREENSHOT_ASSET_ID],
              primary_visual_asset_id: SCREENSHOT_ASSET_ID,
            },
            {
              scene_id: 'e3dfb8bb-048c-4d92-80c3-e72e07740b62',
              sequence: 1,
              module_id: 'source_video',
              narration_segment_id: null,
              source_video_asset_id: SOURCE_VIDEO_ASSET_ID,
              speaker_id: null,
              host_visibility: 'hidden',
              host_slot: null,
              host_enter: false,
              host_exit: false,
              transition_type: 'crossfade',
              variant_id: 'source_video_clean',
              visual_asset_ids: [],
              primary_visual_asset_id: null,
            },
          ]
        : [
            {
          scene_id: SCENE_ID,
          sequence: 0,
          module_id: moduleId,
          narration_segment_id: SEGMENT_ID,
          source_video_asset_id: null,
          speaker_id: 'template-lab-host',
          host_visibility: hostVisible ? 'visible' : 'hidden',
          host_slot: hostSlot,
          host_enter: hostVisible,
          host_exit: hostVisible,
          transition_type: 'crossfade',
          variant_id: variantId,
          visual_asset_ids: [fixture.assetId],
          primary_visual_asset_id: fixture.assetId,
            },
          ],
    },
    source_videos: isSourceVideo ? [sourceVideo] : [],
    visual_assets: isSourceVideo ? [fallbackScreenshot] : [asset],
    template,
    output_profiles: [
      {
        profile_id: 'douyin_vertical',
        width: 1080,
        height: 1920,
        fps: 30,
        layout: 'vertical',
      },
      {
        profile_id: 'bilibili_horizontal',
        width: 1920,
        height: 1080,
        fps: 30,
        layout: 'horizontal',
      },
    ],
    runtime_assets: {
      audio_by_segment_id: {},
      host_video_by_segment_id:
        hostVisible && hostVideoUrl ? {[SEGMENT_ID]: hostVideoUrl} : {},
      visual_by_asset_id: isSourceVideo
        ? {[SCREENSHOT_ASSET_ID]: fallbackScreenshot.local_path}
        : {[fixture.assetId]: fixture.assetUrl},
      output_profile_id: options.profileId,
    },
  };

  try {
    const props = parseGodNewsVideoProps(raw);
    return {
      props,
      available: !fatalDiagnostic,
      diagnostics,
      fixture,
    };
  } catch (error) {
    return {
      props: null,
      available: false,
      diagnostics: [
        `Fixture 未通过生产 Schema：${error instanceof Error ? error.message : String(error)}`,
      ],
      fixture,
    };
  }
};
