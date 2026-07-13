import {z} from 'zod';

const nonBlank = z.string().trim().min(1);
const localPath = nonBlank.max(4096);

// Keep this vocabulary shared with the backend manifest.  The renderer still
// deliberately uses a black placeholder for every value today; retaining the
// semantic tag means a future transition adapter can change visuals without
// rewriting approved narration manifests.
export const SceneTransitionSchema = z.enum([
  'black',
  'crossfade',
  'slide',
  'wipe',
  'mood_shift',
]);

export const TimelineSegmentSchema = z
  .object({
    segment_id: z.string().uuid(),
    sequence: z.number().int().nonnegative(),
    start_ms: z.number().int().nonnegative(),
    end_ms: z.number().int().positive(),
    text: nonBlank,
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
  });

export const ProductionManifestSchema = z
  .object({
    schema_version: z.literal('1.0'),
    story_id: z.string().uuid(),
    script_revision: z.number().int().positive(),
    language: nonBlank,
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
    live2d: Live2DReservationSchema.optional(),
    differential_art: DifferentialArtReservationSchema.optional(),
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
    bgm: BgmSchema.optional(),
    visual_reservations: VisualReservationsSchema.default({renderer: 'placeholder'}),
    runtime_assets: RuntimeAssetsSchema.default({audio_by_segment_id: {}}),
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
  });

export const parseGodNewsVideoProps = (input: unknown): GodNewsVideoProps =>
  ValidatedGodNewsVideoPropsSchema.parse(input);

export type TimelineSegment = z.infer<typeof TimelineSegmentSchema>;
export type SceneTransition = z.infer<typeof SceneTransitionSchema>;
export type ProductionManifest = z.infer<typeof ProductionManifestSchema>;
export type GodNewsVideoProps = z.infer<typeof GodNewsVideoPropsSchema>;
