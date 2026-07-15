import {z} from 'zod';

const nonBlank = z.string().trim().min(1);
const localPath = nonBlank.max(4096);

export const OutputProfileIdSchema = z.enum([
  'douyin_vertical',
  'bilibili_horizontal',
]);

export const OutputProfileSchema = z
  .object({
    profile_id: OutputProfileIdSchema,
    width: z.number().int().positive().max(7680),
    height: z.number().int().positive().max(7680),
    fps: z.number().int().min(1).max(120).default(30),
    layout: z.enum(['vertical', 'horizontal']),
  })
  .strict()
  .superRefine((profile, context) => {
    if (profile.width % 2 !== 0 || profile.height % 2 !== 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'H.264 output dimensions must be even',
      });
    }
    if (profile.layout === 'vertical' && profile.width >= profile.height) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'vertical output profiles require width < height',
      });
    }
    if (profile.layout === 'horizontal' && profile.width <= profile.height) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'horizontal output profiles require width > height',
      });
    }
  });

export const defaultOutputProfiles = (): z.output<typeof OutputProfileSchema>[] => [
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
];

// Keep this vocabulary shared with the backend manifest. Renderers map these
// semantic tags to registered visual transitions; black remains the safe
// fallback and no LLM controls low-level frame or pixel parameters.
export const SceneTransitionSchema = z.enum([
  'black',
  'crossfade',
  'slide',
  'wipe',
  'mood_shift',
]);

export const CaptionVariantSchema = z
  .object({
    language: nonBlank,
    kind: z.enum(['verbatim', 'translation']),
    text: nonBlank,
  })
  .strict();

export const TimedCaptionCueSchema = z
  .object({
    cue_id: z.string().uuid(),
    sequence: z.number().int().nonnegative(),
    start_ms: z.number().int().nonnegative(),
    end_ms: z.number().int().positive(),
    captions: z.array(CaptionVariantSchema).min(1).max(20),
    average_log_probability: z.number().nullable().optional(),
    no_speech_probability: z.number().min(0).max(1).nullable().optional(),
  })
  .strict()
  .refine((cue) => cue.end_ms > cue.start_ms, {
    message: 'caption cue end_ms must be greater than start_ms',
    path: ['end_ms'],
  });

export const SourceVideoRenderAssetSchema = z
  .object({
    asset_id: z.string().uuid(),
    story_id: z.string().uuid(),
    transcription_id: z.string().uuid(),
    transcription_version: z.number().int().min(2),
    transcription_review: z
      .object({
        reviewer_id: nonBlank,
        decision: z.literal('approve'),
        reviewed_version: z.number().int().positive(),
        note: z.string().nullable().optional(),
        reviewed_at: nonBlank,
      })
      .strict(),
    local_path: localPath,
    sha256: z.string().regex(/^[a-f0-9]{64}$/u),
    size_bytes: z.number().int().positive(),
    duration_ms: z.number().int().positive(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    in_ms: z.number().int().nonnegative().default(0),
    out_ms: z.number().int().positive(),
    audio_mode: z.enum(['original', 'muted']).default('original'),
    source_label: nonBlank,
    captions: z.array(TimedCaptionCueSchema).min(1).max(10_000),
  })
  .strict()
  .superRefine((asset, context) => {
    if (asset.out_ms <= asset.in_ms || asset.out_ms > asset.duration_ms) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source video selection must stay inside verified duration',
        path: ['out_ms'],
      });
    }
    if (asset.transcription_version !== asset.transcription_review.reviewed_version + 1) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source video requires the final approved transcription version',
        path: ['transcription_version'],
      });
    }
    const finalCue = asset.captions.at(-1);
    if (finalCue && finalCue.end_ms > asset.duration_ms + 2000) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source video captions extend beyond verified duration',
        path: ['captions'],
      });
    }
  });

export const TimelineSegmentSchema = z
  .object({
    segment_id: z.string().uuid(),
    sequence: z.number().int().nonnegative(),
    start_ms: z.number().int().nonnegative(),
    end_ms: z.number().int().positive(),
    spoken_text: nonBlank,
    spoken_language: nonBlank,
    captions: z.array(CaptionVariantSchema).min(1).max(20),
    speaker_id: nonBlank,
    emotion: nonBlank,
    // Outgoing transition: rendered after this segment and before the next.
    // The last segment retains the value as audit data but has no transition.
    scene_transition: SceneTransitionSchema.default('black'),
    visual_hint: z.string().nullable().optional(),
    audio_path: localPath,
  })
  .strict()
  .refine((segment) => segment.end_ms > segment.start_ms, {
    message: 'end_ms must be greater than start_ms',
    path: ['end_ms'],
  })
  .superRefine((segment, context) => {
    const keys = new Set<string>();
    const verbatim = segment.captions.filter((caption) => caption.kind === 'verbatim');
    for (const [index, caption] of segment.captions.entries()) {
      const key = `${caption.language.toLocaleLowerCase()}\u0000${caption.kind}`;
      if (keys.has(key)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'caption language and kind pairs must be unique',
          path: ['captions', index],
        });
      }
      keys.add(key);
    }
    if (verbatim.length !== 1) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'exactly one verbatim caption is required',
        path: ['captions'],
      });
      return;
    }
    const verbatimCaption = verbatim[0];
    if (verbatimCaption === undefined) return;
    if (
      verbatimCaption.text !== segment.spoken_text ||
      verbatimCaption.language.toLocaleLowerCase() !== segment.spoken_language.toLocaleLowerCase()
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'verbatim caption must match spoken text and language',
        path: ['captions'],
      });
    }
  });

export const ProductionManifestSchema = z
  .object({
    schema_version: z.enum(['1.0', '2.0']),
    story_id: z.string().uuid(),
    script_revision: z.number().int().positive(),
    spoken_language: nonBlank,
    total_duration_ms: z.number().int().positive(),
    timeline: z.array(TimelineSegmentSchema).min(1).max(100),
  })
  .strict()
  .superRefine((manifest, context) => {
    const ids = new Set<string>();
    let expectedStart = 0;

    manifest.timeline.forEach((segment, index) => {
      if (segment.sequence !== index) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'timeline sequence must be contiguous and zero-based',
          path: ['timeline', index, 'sequence'],
        });
      }
      if (segment.start_ms !== expectedStart) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'timeline must be contiguous and start at zero',
          path: ['timeline', index, 'start_ms'],
        });
      }
      if (ids.has(segment.segment_id)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'timeline segment_id values must be unique',
          path: ['timeline', index, 'segment_id'],
        });
      }
      ids.add(segment.segment_id);
      expectedStart = segment.end_ms;
    });

    if (expectedStart !== manifest.total_duration_ms) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'total_duration_ms must equal the final segment end_ms',
        path: ['total_duration_ms'],
      });
    }
  });

export const EpisodeSceneModuleSchema = z.enum([
  'host_evidence',
  'evidence_fullscreen',
  'source_video',
]);

export const EpisodeSceneSchema = z
  .object({
    scene_id: z.string().uuid(),
    sequence: z.number().int().nonnegative().max(99),
    module_id: EpisodeSceneModuleSchema,
    narration_segment_id: z.string().uuid().nullable().optional(),
    source_video_asset_id: z.string().uuid().nullable().optional(),
    speaker_id: nonBlank.nullable().optional(),
    host_visibility: z.enum(['visible', 'hidden']),
    host_slot: z.enum(['primary', 'corner']).nullable().optional(),
    host_enter: z.boolean().default(false),
    host_exit: z.boolean().default(false),
    transition_type: SceneTransitionSchema.default('black'),
  })
  .strict()
  .superRefine((scene, context) => {
    if (scene.host_visibility === 'visible' && !scene.host_slot) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'visible episode hosts require a semantic slot',
        path: ['host_slot'],
      });
    }
    if (scene.host_visibility === 'hidden' && scene.host_slot) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'hidden episode hosts cannot reserve a visual slot',
        path: ['host_slot'],
      });
    }
    if (scene.module_id === 'host_evidence' && scene.host_visibility !== 'visible') {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'host_evidence requires a visible host',
        path: ['host_visibility'],
      });
    }
    if (scene.module_id === 'evidence_fullscreen' && scene.host_visibility !== 'hidden') {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'evidence_fullscreen requires a hidden host',
        path: ['host_visibility'],
      });
    }
    if (scene.module_id === 'source_video') {
      if (scene.host_visibility !== 'hidden') {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'source_video requires a hidden host',
          path: ['host_visibility'],
        });
      }
      if (scene.narration_segment_id || !scene.source_video_asset_id || scene.speaker_id) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'source_video requires only a source video asset',
          path: ['source_video_asset_id'],
        });
      }
    } else if (
      !scene.narration_segment_id ||
      scene.source_video_asset_id ||
      !scene.speaker_id
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'narration scenes require one segment and one speaker',
        path: ['narration_segment_id'],
      });
    }
  });

export const EpisodePlanSchema = z
  .object({
    schema_version: z.literal('1.0').default('1.0'),
    batch_id: z.string().uuid(),
    scenes: z.array(EpisodeSceneSchema).min(1).max(100),
  })
  .strict()
  .superRefine((plan, context) => {
    const sceneIds = new Set<string>();
    const segmentIds = new Set<string>();
    plan.scenes.forEach((scene, index) => {
      if (scene.sequence !== index) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'episode scene sequence must be contiguous and zero-based',
          path: ['scenes', index, 'sequence'],
        });
      }
      if (sceneIds.has(scene.scene_id)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'episode scene IDs must be unique',
          path: ['scenes', index, 'scene_id'],
        });
      }
      if (
        scene.narration_segment_id &&
        segmentIds.has(scene.narration_segment_id)
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'narration segments may appear in only one episode scene',
          path: ['scenes', index, 'narration_segment_id'],
        });
      }
      sceneIds.add(scene.scene_id);
      if (scene.narration_segment_id) {
        segmentIds.add(scene.narration_segment_id);
      }
    });
  });

const ThemeSchema = z
  .object({
    background: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#101512'),
    foreground: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#f3f1e8'),
    accent: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#85a77d'),
    signal: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#e4a853'),
  })
  .strict();

const Live2DReservationSchema = z
  .object({
    character_id: nonBlank,
    model_json_path: localPath,
    idle_motion_group: nonBlank.optional(),
  })
  .strict();

const DifferentialArtReservationSchema = z
  .object({
    base_image_path: localPath,
    layers: z
      .array(
        z
          .object({
            layer_id: nonBlank,
            image_path: localPath,
            z_index: z.number().int(),
          })
          .strict(),
      )
      .max(64)
      .default([]),
  })
  .strict();

const VisualReservationsSchema = z
  .object({
    renderer: z.literal('placeholder').default('placeholder'),
    live2d: Live2DReservationSchema.nullable().optional(),
    differential_art: DifferentialArtReservationSchema.nullable().optional(),
  })
  .strict();

export const BgmSchema = z
  .object({
    local_path: localPath,
    volume: z.number().min(0).max(1).default(0.12),
    loop: z.boolean().default(true),
  })
  .strict();

const RuntimeAssetsSchema = z
  .object({
    audio_by_segment_id: z.record(z.string().uuid(), nonBlank).default({}),
    bgm_src: nonBlank.optional(),
    output_profile_id: OutputProfileIdSchema.default('douyin_vertical'),
  })
  .strict();

// Remotion deliberately requires the top-level schema to remain a ZodObject.
// Cross-field invariants therefore live in the validated wrapper below.
export const GodNewsVideoPropsSchema = z
  .object({
    manifest: ProductionManifestSchema,
    title: nonBlank.max(240),
    subtitle: z.string().trim().max(320).nullable().optional(),
    intro_duration_ms: z.number().int().min(0).max(5000).default(700),
    transition_duration_ms: z.number().int().min(0).max(2000).default(180),
    theme: ThemeSchema.default({
      background: '#101512',
      foreground: '#f3f1e8',
      accent: '#85a77d',
      signal: '#e4a853',
    }),
    bgm: BgmSchema.nullable().optional(),
    visual_reservations: VisualReservationsSchema.default({renderer: 'placeholder'}),
    episode_plan: EpisodePlanSchema.nullable().optional(),
    source_videos: z.array(SourceVideoRenderAssetSchema).max(100).default([]),
    output_profiles: z.array(OutputProfileSchema).min(1).max(8).default(defaultOutputProfiles),
    runtime_assets: RuntimeAssetsSchema.default({
      audio_by_segment_id: {},
      output_profile_id: 'douyin_vertical',
    }),
  })
  .strict();

const ValidatedGodNewsVideoPropsSchema = GodNewsVideoPropsSchema
  .superRefine((props, context) => {
    const segmentIds = new Set(
      props.manifest.timeline.map((segment) => segment.segment_id),
    );
    for (const segmentId of Object.keys(props.runtime_assets.audio_by_segment_id)) {
      if (!segmentIds.has(segmentId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'runtime audio binding references an unknown segment_id',
          path: ['runtime_assets', 'audio_by_segment_id', segmentId],
        });
      }
    }
    if (props.runtime_assets.bgm_src && !props.bgm) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'runtime bgm_src requires bgm configuration',
        path: ['runtime_assets', 'bgm_src'],
      });
    }
    const profileIds = props.output_profiles.map((profile) => profile.profile_id);
    if (new Set(profileIds).size !== profileIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'output profile IDs must be unique',
        path: ['output_profiles'],
      });
    }
    for (const requiredProfile of [
      'douyin_vertical',
      'bilibili_horizontal',
    ] as const) {
      if (!profileIds.includes(requiredProfile)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: `required output profile is missing: ${requiredProfile}`,
          path: ['output_profiles'],
        });
      }
    }
    if (!profileIds.includes(props.runtime_assets.output_profile_id)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'runtime output profile is not declared by the semantic render snapshot',
        path: ['runtime_assets', 'output_profile_id'],
      });
    }
    if (props.episode_plan) {
      if (props.episode_plan.batch_id !== props.manifest.story_id) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'episode plan must be owned by the rendered batch',
          path: ['episode_plan', 'batch_id'],
        });
      }
      const timeline = props.manifest.timeline;
      const narrationScenes = props.episode_plan.scenes.filter(
        (scene) => scene.narration_segment_id,
      );
      if (narrationScenes.length !== timeline.length) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'episode plan must cover every narration segment',
          path: ['episode_plan', 'scenes'],
        });
      } else {
        narrationScenes.forEach((scene, index) => {
          const segment = timeline[index];
          if (
            !segment ||
            scene.narration_segment_id !== segment.segment_id ||
            scene.speaker_id !== segment.speaker_id ||
            scene.transition_type !== segment.scene_transition
          ) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'episode scene identity must match reviewed narration',
              path: ['episode_plan', 'scenes', index],
            });
          }
        });
      }
      const assetIds = props.source_videos.map((asset) => asset.asset_id);
      if (new Set(assetIds).size !== assetIds.length) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'source video asset IDs must be unique',
          path: ['source_videos'],
        });
      }
      const referencedAssetIds = new Set(
        props.episode_plan.scenes.flatMap((scene) =>
          scene.source_video_asset_id ? [scene.source_video_asset_id] : [],
        ),
      );
      if (
        referencedAssetIds.size !== assetIds.length ||
        assetIds.some((assetId) => !referencedAssetIds.has(assetId))
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'episode source video scenes must match approved assets',
          path: ['source_videos'],
        });
      }
    } else if (props.source_videos.length > 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source video assets require a typed episode plan',
        path: ['source_videos'],
      });
    }
  });

export const parseGodNewsVideoProps = (input: unknown): GodNewsVideoProps =>
  ValidatedGodNewsVideoPropsSchema.parse(input);

export type TimelineSegment = z.infer<typeof TimelineSegmentSchema>;
export type SceneTransition = z.infer<typeof SceneTransitionSchema>;
export type OutputProfileId = z.infer<typeof OutputProfileIdSchema>;
export type OutputProfile = z.infer<typeof OutputProfileSchema>;
export type VideoTheme = z.infer<typeof ThemeSchema>;
export type ProductionManifest = z.infer<typeof ProductionManifestSchema>;
export type EpisodePlan = z.infer<typeof EpisodePlanSchema>;
export type EpisodeScene = z.infer<typeof EpisodeSceneSchema>;
export type EpisodeSceneModule = z.infer<typeof EpisodeSceneModuleSchema>;
export type SourceVideoRenderAsset = z.infer<typeof SourceVideoRenderAssetSchema>;
export type GodNewsVideoProps = z.infer<typeof GodNewsVideoPropsSchema>;
