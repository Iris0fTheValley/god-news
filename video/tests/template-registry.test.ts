import {describe, expect, it} from 'vitest';

import {createTemplateLabFixture} from '../src/lab/fixtures';
import {compileSceneLayout} from '../src/layout/compile-layout';
import {parseGodNewsVideoProps} from '../src/schema';
import {captionFontScale} from '../src/shared/AdaptiveCaptionText';
import {SceneModuleRegistry, TemplateRegistry} from '../src/templates/registry';
import {worldWarmthTemplate} from '../src/templates/world-warmth';

const Dummy = () => null;

describe('versioned template and layout registries', () => {
  it('rejects duplicate scene module registrations', () => {
    expect(
      () =>
        new SceneModuleRegistry([
          {moduleId: 'host_evidence', variants: {host_split_editorial: Dummy}},
          {moduleId: 'host_evidence', variants: {host_split_editorial: Dummy}},
        ]),
    ).toThrow(/Duplicate scene module/u);
  });

  it('rejects a template that references an unregistered variant', () => {
    const modules = new SceneModuleRegistry([
      {moduleId: 'host_evidence', variants: {host_split_editorial: Dummy}},
      {moduleId: 'evidence_fullscreen', variants: {evidence_documentary: Dummy}},
      {moduleId: 'source_video', variants: {source_video_clean: Dummy}},
    ]);
    const invalid = {
      ...worldWarmthTemplate,
      scene_variants: worldWarmthTemplate.scene_variants.map((variant) =>
        variant.variant_id === 'host_corner_full_bleed'
          ? {...variant, variant_id: 'missing_renderer'}
          : variant,
      ),
    };

    expect(() => new TemplateRegistry([invalid], modules)).toThrow(
      /unregistered scene variant/u,
    );
  });

  it('rejects template capability/layout profile drift', () => {
    const result = createTemplateLabFixture({
      fixtureId: 'evidence-source-page',
      profileId: 'bilibili_horizontal',
    });
    expect(result.props).not.toBeNull();
    const missingLayout = structuredClone(result.props!);
    missingLayout.template!.layout_preset.profiles =
      missingLayout.template!.layout_preset.profiles.filter(
        (profile) => profile.profile_id !== 'bilibili_horizontal',
      );
    expect(() => parseGodNewsVideoProps(missingLayout)).toThrow(
      /layout profiles must match capability profiles/u,
    );

    const duplicateCapability = structuredClone(result.props!);
    duplicateCapability.template!.capabilities.supported_profiles = [
      'douyin_vertical',
      'douyin_vertical',
    ];
    expect(() => parseGodNewsVideoProps(duplicateCapability)).toThrow(
      /capability profiles must be unique/u,
    );
  });

  it('compiles different layouts from one semantic scene', () => {
    const horizontal = createTemplateLabFixture({
      fixtureId: 'evidence-source-page',
      profileId: 'bilibili_horizontal',
    });
    const vertical = createTemplateLabFixture({
      fixtureId: 'evidence-source-page',
      profileId: 'douyin_vertical',
    });
    expect(horizontal.props).not.toBeNull();
    expect(vertical.props).not.toBeNull();
    if (!horizontal.props?.episode_plan || !vertical.props?.episode_plan) return;

    const horizontalLayout = compileSceneLayout(
      horizontal.props,
      horizontal.props.episode_plan.scenes[0]!,
    );
    const verticalLayout = compileSceneLayout(
      vertical.props,
      vertical.props.episode_plan.scenes[0]!,
    );

    expect(horizontalLayout.media.width).not.toBe(verticalLayout.media.width);
    expect(horizontalLayout.caption.height).not.toBe(verticalLayout.caption.height);
    expect(horizontalLayout.variant.variant_id).toBe(
      verticalLayout.variant.variant_id,
    );
  });

  it('fails fixture validation when a required visual is removed', () => {
    const result = createTemplateLabFixture({
      fixtureId: 'evidence-source-page',
      profileId: 'bilibili_horizontal',
    });
    expect(result.props).not.toBeNull();
    const raw = structuredClone(result.props!);
    raw.episode_plan!.scenes[0]!.visual_asset_ids = [];
    raw.episode_plan!.scenes[0]!.primary_visual_asset_id = null;

    expect(() => parseGodNewsVideoProps(raw)).toThrow(/visual asset count/u);
  });

  it('rejects a host slot not declared by the selected scene variant', () => {
    const result = createTemplateLabFixture({
      fixtureId: 'host-corner-volunteers',
      profileId: 'bilibili_horizontal',
      hostVideoUrl: '/template-lab/host-soyo-30fps.webm',
    });
    expect(result.props?.episode_plan).not.toBeNull();
    const raw = structuredClone(result.props!);
    raw.episode_plan!.scenes[0]!.host_slot = 'primary';

    expect(() => parseGodNewsVideoProps(raw)).toThrow(
      /unsupported host slot/u,
    );
  });

  it('uses the production source-video scene for the finite owned clip fixture', () => {
    const result = createTemplateLabFixture({
      fixtureId: 'source-video-owned',
      profileId: 'bilibili_horizontal',
    });

    expect(result.available).toBe(true);
    expect(result.props?.source_videos).toHaveLength(1);
    expect(
      result.props?.episode_plan?.scenes.some(
        (scene) => scene.module_id === 'source_video',
      ),
    ).toBe(true);
    expect(result.props?.source_videos[0]?.local_path).toBe(
      '/template-lab/project-owned-source.mp4',
    );
  });

  it('reports a profile-aware warning for a vertically constrained caption', () => {
    const result = createTemplateLabFixture({
      fixtureId: 'evidence-long-caption',
      profileId: 'douyin_vertical',
    });

    expect(result.available).toBe(true);
    expect(result.diagnostics).toContain(
      '中文字幕超过当前比例建议的 42 个字符，请检查双行截断和安全区。',
    );
  });

  it('shrinks a long caption within the three-line contract and rejects unreadable text', () => {
    const scale = captionFontScale({
      text: '当邻里共同保护一处可自由进入的公共空间，那些看似微小的善意就不再只是偶然，而会在阅读、相遇和互相帮助中继续发生。',
      charactersPerLine: 16,
      maxLines: 3,
    });
    expect(scale).toBeGreaterThanOrEqual(0.55);
    expect(scale).toBeLessThan(1);
    expect(() =>
      captionFontScale({
        text: '过长字幕'.repeat(40),
        charactersPerLine: 18,
        maxLines: 2,
      }),
    ).toThrow(/exceeds renderable capacity/u);
  });
});
