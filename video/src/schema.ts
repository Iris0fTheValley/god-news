import {z} from 'zod';

const nonBlank = z.string().trim().min(1);
const localPath = nonBlank.max(4096);
const sha256 = z.string().regex(/^[a-f0-9]{64}$/u);

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
    sha256,
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

export const VisualAssetTypeSchema = z.enum([
  'image',
  'source_screenshot',
  'web_evidence',
  'source_video',
  'map',
  'chart',
  'document',
  'host_video',
  'background_video',
  'decorative_overlay',
]);

export const VisualRenderAssetSchema = z
  .object({
    asset_id: z.string().uuid(),
    story_id: z.string().uuid(),
    segment_id: z.string().uuid().nullable().optional(),
    asset_type: VisualAssetTypeSchema,
    content_type: nonBlank,
    filename: nonBlank,
    local_path: localPath,
    sha256,
    size_bytes: z.number().int().positive(),
    width: z.number().int().positive().max(16_384),
    height: z.number().int().positive().max(16_384),
    source_label: nonBlank,
    source_url: z.string().url().nullable().optional(),
  })
  .strict()
  .superRefine((asset, context) => {
    if (asset.asset_type === 'image' && !asset.segment_id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'editor images must bind to a narration segment',
        path: ['segment_id'],
      });
    }
    if (asset.asset_type === 'source_screenshot' && asset.segment_id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source screenshots are story-level evidence',
        path: ['segment_id'],
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
    variant_id: z.string().regex(/^[a-z][a-z0-9_]{1,63}$/u).nullable().optional(),
    visual_asset_ids: z.array(z.string().uuid()).max(12).default([]),
    primary_visual_asset_id: z.string().uuid().nullable().optional(),
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
    if (new Set(scene.visual_asset_ids).size !== scene.visual_asset_ids.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'scene visual asset IDs must be unique',
        path: ['visual_asset_ids'],
      });
    }
    if (
      scene.primary_visual_asset_id &&
      !scene.visual_asset_ids.includes(scene.primary_visual_asset_id)
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'primary visual asset must belong to the scene visual asset set',
        path: ['primary_visual_asset_id'],
      });
    }
    if (scene.module_id === 'source_video' && scene.visual_asset_ids.length > 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source_video scenes use only their source video asset',
        path: ['visual_asset_ids'],
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

const TemplateAssetRequirementSchema = z
  .object({
    asset_type: VisualAssetTypeSchema,
    required: z.boolean().default(true),
    minimum: z.number().int().min(0).max(12).default(1),
    maximum: z.number().int().min(1).max(12).default(1),
  })
  .strict()
  .superRefine((requirement, context) => {
    if (requirement.minimum > requirement.maximum) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template asset minimum cannot exceed maximum',
        path: ['minimum'],
      });
    }
    if (requirement.required && requirement.minimum === 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'required template assets require at least one item',
        path: ['minimum'],
      });
    }
  });

export const SceneVariantDefinitionSchema = z
  .object({
    variant_id: z.string().regex(/^[a-z][a-z0-9_]{1,63}$/u),
    module_id: EpisodeSceneModuleSchema,
    display_name: nonBlank,
    supported_profiles: z.array(OutputProfileIdSchema).min(1).max(8),
    supported_host_slots: z.array(z.enum(['primary', 'corner'])).max(8).default([]),
    asset_requirements: z.array(TemplateAssetRequirementSchema).max(12).default([]),
    minimum_visual_assets: z.number().int().min(0).max(12).default(0),
    maximum_visual_assets: z.number().int().min(0).max(12).default(12),
  })
  .strict()
  .refine(
    (variant) => variant.minimum_visual_assets <= variant.maximum_visual_assets,
    {
      message: 'scene variant visual asset range is invalid',
      path: ['maximum_visual_assets'],
    },
  );

const OutputProfileLayoutSchema = z
  .object({
    profile_id: OutputProfileIdSchema,
    safe_area_top: z.number().min(0).max(0.25),
    safe_area_right: z.number().min(0).max(0.25),
    safe_area_bottom: z.number().min(0).max(0.35),
    safe_area_left: z.number().min(0).max(0.25),
    host_primary_width: z.number().positive().max(0.8),
    host_corner_width: z.number().positive().max(0.6),
    caption_max_width: z.number().positive().max(1),
    media_fit: z.enum(['contain', 'cover']).default('cover'),
  })
  .strict();

const LayoutPresetSchema = z
  .object({
    preset_id: nonBlank,
    profiles: z.array(OutputProfileLayoutSchema).min(1).max(8),
  })
  .strict();

export const DesignTokensSchema = z
  .object({
    font_family: nonBlank,
    title_font_family: nonBlank,
    body_font_family: nonBlank,
    caption_font_family: nonBlank,
    mono_font_family: nonBlank,
    background: z.string().regex(/^#[0-9a-fA-F]{6}$/u),
    foreground: z.string().regex(/^#[0-9a-fA-F]{6}$/u),
    accent: z.string().regex(/^#[0-9a-fA-F]{6}$/u),
    signal: z.string().regex(/^#[0-9a-fA-F]{6}$/u),
    panel: z.string().regex(/^#[0-9a-fA-F]{6}$/u),
    muted: z.string().regex(/^#[0-9a-fA-F]{6}$/u),
    title_scale: z.number().min(0.5).max(2),
    body_scale: z.number().min(0.5).max(2),
    caption_scale: z.number().min(0.5).max(2),
    title_weight: z.number().int().min(100).max(900),
    body_weight: z.number().int().min(100).max(900),
    caption_weight: z.number().int().min(100).max(900),
    line_height: z.number().min(0.9).max(2),
    corner_radius: z.number().int().min(0).max(120),
    border_width: z.number().int().min(0).max(12),
    shadow_blur: z.number().int().min(0).max(160),
    panel_opacity: z.number().min(0).max(1),
    spacing_unit: z.number().int().min(2).max(32),
    caption_max_lines: z.number().int().min(1).max(4),
    animation_speed: z.number().min(0.25).max(3),
    animation_easing: nonBlank,
    image_zoom_min: z.number().min(0.5).max(2),
    image_zoom_max: z.number().min(0.5).max(2),
  })
  .strict()
  .refine((tokens) => tokens.image_zoom_max >= tokens.image_zoom_min, {
    message: 'image zoom maximum cannot be below its minimum',
    path: ['image_zoom_max'],
  });

const TemplateCapabilitiesSchema = z
  .object({
    supported_profiles: z.array(OutputProfileIdSchema).min(1).max(8),
    supported_modules: z.array(EpisodeSceneModuleSchema).min(1).max(32),
    supports_bilingual_captions: z.boolean().default(true),
    supports_live2d: z.boolean().default(true),
    supports_source_attribution: z.boolean().default(true),
  })
  .strict();

export const TemplateDefinitionSchema = z
  .object({
    template_id: z.string().regex(/^[a-z][a-z0-9_]{1,63}$/u),
    template_version: z
      .string()
      .regex(/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u),
    display_name: nonBlank,
    capabilities: TemplateCapabilitiesSchema,
    scene_variants: z.array(SceneVariantDefinitionSchema).min(1).max(64),
    default_scene_variants: z.record(
      EpisodeSceneModuleSchema,
      z.string().regex(/^[a-z][a-z0-9_]{1,63}$/u),
    ),
    layout_preset: LayoutPresetSchema,
    design_tokens: DesignTokensSchema,
    intro_variant: nonBlank,
    outro_variant: nonBlank,
    transition_pack: nonBlank,
    caption_preset: nonBlank,
    source_bar_preset: nonBlank,
    host_preset: nonBlank,
    static_asset_requirements: z.array(nonBlank).max(64).default([]),
  })
  .strict()
  .superRefine((template, context) => {
    const supportedProfiles = template.capabilities.supported_profiles;
    if (new Set(supportedProfiles).size !== supportedProfiles.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template capability profiles must be unique',
        path: ['capabilities', 'supported_profiles'],
      });
    }
    const supportedModules = template.capabilities.supported_modules;
    if (new Set(supportedModules).size !== supportedModules.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template capability modules must be unique',
        path: ['capabilities', 'supported_modules'],
      });
    }
    const layoutProfiles = template.layout_preset.profiles.map(
      (profile) => profile.profile_id,
    );
    if (new Set(layoutProfiles).size !== layoutProfiles.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template layout profiles must be unique',
        path: ['layout_preset', 'profiles'],
      });
    }
    if (
      supportedProfiles.length !== layoutProfiles.length ||
      supportedProfiles.some((profile) => !layoutProfiles.includes(profile))
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template layout profiles must match capability profiles',
        path: ['layout_preset', 'profiles'],
      });
    }
    const variantIds = template.scene_variants.map((variant) => variant.variant_id);
    if (new Set(variantIds).size !== variantIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template scene variant IDs must be unique',
        path: ['scene_variants'],
      });
    }
    for (const [index, variant] of template.scene_variants.entries()) {
      if (!supportedModules.includes(variant.module_id)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'template scene variant uses an unsupported module',
          path: ['scene_variants', index, 'module_id'],
        });
      }
      if (
        variant.supported_profiles.some(
          (profile) => !supportedProfiles.includes(profile),
        )
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'template scene variant uses an unsupported profile',
          path: ['scene_variants', index, 'supported_profiles'],
        });
      }
    }
    const defaults = Object.entries(template.default_scene_variants);
    if (defaults.length !== template.capabilities.supported_modules.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'template defaults must cover supported modules',
        path: ['default_scene_variants'],
      });
    }
    for (const [moduleId, variantId] of defaults) {
      const variant = template.scene_variants.find(
        (candidate) => candidate.variant_id === variantId,
      );
      if (!variant || variant.module_id !== moduleId) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'template default scene variant reference is invalid',
          path: ['default_scene_variants', moduleId],
        });
      }
    }
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

const Live2DSignalMetricsSchema = z
  .object({
    samples: z.number().int().positive(),
    duration_seconds: z.number().positive(),
    minimum: z.number(),
    maximum: z.number(),
    p95_absolute_value: z.number().nonnegative(),
    p99_absolute_value: z.number().nonnegative(),
    maximum_absolute_value: z.number().nonnegative(),
    p95_absolute_step: z.number().nonnegative(),
    p99_absolute_step: z.number().nonnegative(),
    maximum_absolute_step: z.number().nonnegative(),
    p95_absolute_velocity: z.number().nonnegative(),
    maximum_absolute_velocity: z.number().nonnegative(),
    p95_absolute_acceleration: z.number().nonnegative(),
    maximum_absolute_acceleration: z.number().nonnegative(),
    p95_absolute_jerk: z.number().nonnegative(),
    maximum_absolute_jerk: z.number().nonnegative(),
    direction_reversals_per_second: z.number().nonnegative(),
    high_frequency_energy_ratio: z.number().nonnegative(),
    alternating_energy_ratio: z.number().min(0).max(1),
  })
  .strict();

const Live2DGateFindingSchema = z
  .object({
    code: nonBlank,
    metric: nonBlank,
    observed: z.number().nonnegative(),
    threshold: z.number().nonnegative(),
  })
  .strict();

const Live2DParameterDiagnosticsSchema = z
  .object({
    range: z
      .object({
        minimum: z.number(),
        maximum: z.number(),
        default: z.number(),
      })
      .strict(),
    metrics: Live2DSignalMetricsSchema,
    threshold: z
      .object({
        maximum_absolute_step: z.number().positive(),
        maximum_absolute_velocity: z.number().positive(),
        maximum_absolute_acceleration: z.number().positive(),
        maximum_absolute_jerk: z.number().positive(),
        maximum_direction_reversals_per_second: z.number().positive(),
        maximum_high_frequency_energy_ratio: z.number().positive(),
      })
      .strict(),
    findings: z.array(Live2DGateFindingSchema).max(32),
  })
  .strict();

const RenderedHostVideoSchema = z
  .object({
    asset_id: z.string().uuid(),
    segment_id: z.string().uuid(),
    speaker_id: nonBlank,
    role_profile_id: z.string().uuid(),
    role_profile_version: z.number().int().min(1),
    model_sha256: sha256,
    audio_sha256: sha256,
    local_path: localPath,
    sha256,
    size_bytes: z.number().int().positive(),
    duration_ms: z.number().int().positive(),
    width: z.number().int().positive().max(4096),
    height: z.number().int().positive().max(4096),
    fps: z.number().int().min(1).max(120),
    video_codec: nonBlank,
    diagnostics: z
      .object({
        schema_version: z.literal('2.0'),
        control_mode: z.enum([
          'legacy_conflict',
          'motion_only',
          'procedural_only',
          'no_lip_sync',
          'final',
        ]),
        frames: z.number().int().positive(),
        envelope_frames: z.number().int().positive(),
        rendered_frames: z.number().int().positive(),
        fps: z.number().int().min(1).max(120),
        time_delta_ms_min: z.number().int().positive(),
        time_delta_ms_max: z.number().int().positive(),
        motion_group: z.string().nullable().optional(),
        motion_restarts: z.number().int().nonnegative(),
        motion_state_counts: z.record(nonBlank, z.number().int().nonnegative()),
        motion_switch_max_delta: z.number().nonnegative(),
        motion_source_switch_max_delta: z.number().nonnegative(),
        motion_metadata: z
          .object({
            file: nonBlank,
            fps: z.number().int().min(1).max(120).nullable().optional(),
            fade_in_ms: z.number().min(0).max(60_000).nullable().optional(),
            fade_out_ms: z.number().min(0).max(60_000).nullable().optional(),
            frames: z.number().int().positive().nullable().optional(),
          })
          .strict()
          .nullable()
          .optional(),
        expression: z.string().nullable().optional(),
        blink_events: z.number().int().nonnegative(),
        mouth_min: z.number().min(0).max(1),
        mouth_p50: z.number().min(0).max(1),
        mouth_p95: z.number().min(0).max(1),
        mouth_max: z.number().min(0).max(1),
        mouth_max_delta: z.number().min(0).max(1),
        voiced_frame_ratio: z.number().min(0).max(1),
        exact_duplicate_pair_ratio: z.number().min(0).max(1),
        longest_exact_duplicate_run: z.number().int().nonnegative(),
        controlled_parameters: z.array(nonBlank).max(32),
        parameter_owners: z.record(nonBlank, nonBlank),
        parameter_metrics: z.record(nonBlank, Live2DParameterDiagnosticsSchema),
        image_metrics: z.record(nonBlank, Live2DSignalMetricsSchema),
        image_thresholds: z.record(nonBlank, z.number()),
        gate_findings: z.array(Live2DGateFindingSchema).max(256),
        quality_gate_passed: z.boolean(),
        audio_calibration: z
          .object({
            noise_floor: z.number().min(0).max(1),
            normalization_peak: z.number().positive().max(1),
          })
          .strict(),
        trace_path: localPath,
        trace_sha256: sha256,
        trace_size_bytes: z.number().int().positive(),
      })
      .strict()
      .nullable()
      .optional(),
  })
  .strict();

const VisualReservationsSchema = z
  .object({
    renderer: z.enum(['placeholder', 'live2d_prerender']).default('placeholder'),
    host_videos: z.array(RenderedHostVideoSchema).max(100).default([]),
    live2d: Live2DReservationSchema.nullable().optional(),
    differential_art: DifferentialArtReservationSchema.nullable().optional(),
  })
  .strict()
  .superRefine((reservation, context) => {
    const segmentIds = reservation.host_videos.map((asset) => asset.segment_id);
    const assetIds = reservation.host_videos.map((asset) => asset.asset_id);
    if (new Set(segmentIds).size !== segmentIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'host videos must be unique by narration segment',
        path: ['host_videos'],
      });
    }
    if (new Set(assetIds).size !== assetIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'host video asset IDs must be unique',
        path: ['host_videos'],
      });
    }
    if (reservation.renderer === 'placeholder' && reservation.host_videos.length > 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'placeholder renderer cannot retain host videos',
        path: ['host_videos'],
      });
    }
    if (reservation.renderer === 'live2d_prerender' && reservation.host_videos.length === 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'Live2D renderer requires host videos',
        path: ['host_videos'],
      });
    }
  });

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
    host_video_by_segment_id: z.record(z.string().uuid(), nonBlank).default({}),
    visual_by_asset_id: z.record(z.string().uuid(), nonBlank).default({}),
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
    outro_duration_ms: z.number().int().min(0).max(10000).default(3000),
    transition_duration_ms: z.number().int().min(0).max(2000).default(180),
    theme: ThemeSchema.default({
      background: '#101512',
      foreground: '#f3f1e8',
      accent: '#85a77d',
      signal: '#e4a853',
    }),
    bgm: BgmSchema.nullable().optional(),
    visual_reservations: VisualReservationsSchema.default({
      renderer: 'placeholder',
      host_videos: [],
    }),
    episode_plan: EpisodePlanSchema.nullable().optional(),
    source_videos: z.array(SourceVideoRenderAssetSchema).max(100).default([]),
    visual_assets: z.array(VisualRenderAssetSchema).max(1200).default([]),
    template: TemplateDefinitionSchema.nullable().optional(),
    output_profiles: z.array(OutputProfileSchema).min(1).max(8).default(defaultOutputProfiles),
    runtime_assets: RuntimeAssetsSchema.default({
      audio_by_segment_id: {},
      host_video_by_segment_id: {},
      visual_by_asset_id: {},
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
    for (const segmentId of Object.keys(props.runtime_assets.host_video_by_segment_id)) {
      if (!segmentIds.has(segmentId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'runtime host-video binding references an unknown segment_id',
          path: ['runtime_assets', 'host_video_by_segment_id', segmentId],
        });
      }
    }
    const visualAssetIds = new Set(props.visual_assets.map((asset) => asset.asset_id));
    for (const assetId of Object.keys(props.runtime_assets.visual_by_asset_id)) {
      if (!visualAssetIds.has(assetId)) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'runtime visual binding references an unknown asset_id',
          path: ['runtime_assets', 'visual_by_asset_id', assetId],
        });
      }
    }
    if (props.visual_reservations.renderer === 'live2d_prerender') {
      const timeline = props.manifest.timeline;
      const hosts = props.visual_reservations.host_videos;
      if (hosts.length !== timeline.length) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'Live2D host videos must cover the narration timeline',
          path: ['visual_reservations', 'host_videos'],
        });
      } else {
        hosts.forEach((host, index) => {
          const segment = timeline[index];
          if (
            !segment ||
            host.segment_id !== segment.segment_id ||
            host.speaker_id !== segment.speaker_id ||
            host.duration_ms !== segment.end_ms - segment.start_ms
          ) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'Live2D host identity and duration must match narration',
              path: ['visual_reservations', 'host_videos', index],
            });
          }
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
      const referencedVisualIds = new Set(
        props.episode_plan.scenes.flatMap((scene) => scene.visual_asset_ids),
      );
      for (const assetId of referencedVisualIds) {
        if (!visualAssetIds.has(assetId)) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            message: 'episode scene references an unknown visual asset',
            path: ['episode_plan', 'scenes'],
          });
        }
      }
      if (props.template) {
        const supportedModules = new Set(props.template.capabilities.supported_modules);
        const variants = new Map(
          props.template.scene_variants.map((variant) => [variant.variant_id, variant]),
        );
        for (const [index, scene] of props.episode_plan.scenes.entries()) {
          if (!supportedModules.has(scene.module_id)) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'episode scene is unsupported by selected template',
              path: ['episode_plan', 'scenes', index, 'module_id'],
            });
          }
          const variantId =
            scene.variant_id ??
            props.template.default_scene_variants[scene.module_id];
          const variant = variantId ? variants.get(variantId) : undefined;
          if (!variant || variant.module_id !== scene.module_id) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'episode scene references an invalid template variant',
              path: ['episode_plan', 'scenes', index, 'variant_id'],
            });
            continue;
          }
          if (
            scene.host_visibility === 'visible' &&
            (!scene.host_slot ||
              !variant.supported_host_slots.includes(scene.host_slot))
          ) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'episode scene uses an unsupported host slot',
              path: ['episode_plan', 'scenes', index, 'host_slot'],
            });
          }
          if (
            scene.host_visibility === 'hidden' &&
            scene.host_slot !== null
          ) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'hidden host scene cannot retain a host slot',
              path: ['episode_plan', 'scenes', index, 'host_slot'],
            });
          }
          if (
            scene.visual_asset_ids.length < variant.minimum_visual_assets ||
            scene.visual_asset_ids.length > variant.maximum_visual_assets
          ) {
            context.addIssue({
              code: z.ZodIssueCode.custom,
              message: 'episode scene violates template visual asset count',
              path: ['episode_plan', 'scenes', index, 'visual_asset_ids'],
            });
          }
          const sceneAssets = scene.visual_asset_ids
            .map((assetId) =>
              props.visual_assets.find((asset) => asset.asset_id === assetId),
            )
            .filter((asset) => asset !== undefined);
          for (const requirement of variant.asset_requirements) {
            const count = sceneAssets.filter(
              (asset) => asset.asset_type === requirement.asset_type,
            ).length;
            if (count < requirement.minimum || count > requirement.maximum) {
              context.addIssue({
                code: z.ZodIssueCode.custom,
                message: 'episode scene violates template asset requirements',
                path: ['episode_plan', 'scenes', index, 'visual_asset_ids'],
              });
            }
          }
        }
      }
    } else if (props.source_videos.length > 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'source video assets require a typed episode plan',
        path: ['source_videos'],
      });
    } else if (props.visual_assets.length > 0) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'visual assets require a typed episode plan',
        path: ['visual_assets'],
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
export type VisualRenderAsset = z.infer<typeof VisualRenderAssetSchema>;
export type VisualAssetType = z.infer<typeof VisualAssetTypeSchema>;
export type TemplateDefinition = z.infer<typeof TemplateDefinitionSchema>;
export type SceneVariantDefinition = z.infer<typeof SceneVariantDefinitionSchema>;
export type GodNewsVideoProps = z.infer<typeof GodNewsVideoPropsSchema>;
