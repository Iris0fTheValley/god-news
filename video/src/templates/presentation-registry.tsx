import type {ComponentType} from 'react';

import type {TransitionTrack} from '../render-plan';
import type {GodNewsVideoProps, VideoTheme} from '../schema';
import {ClosingCard} from '../scenes/ClosingCard';
import {TitleCard} from '../scenes/TitleCard';
import {TransitionScene} from '../scenes/TransitionScene';

type IntroRendererProps = Readonly<{
  title: string;
  subtitle?: string;
  theme: VideoTheme;
}>;
type OutroRendererProps = Readonly<{title: string; theme: VideoTheme}>;
type TransitionRendererProps = Readonly<{
  track: TransitionTrack;
  theme: VideoTheme;
}>;

class ComponentRegistry<Props> {
  readonly #components: ReadonlyMap<string, ComponentType<Props>>;
  readonly #label: string;

  constructor(
    label: string,
    definitions: readonly Readonly<{
      id: string;
      component: ComponentType<Props>;
    }>[],
  ) {
    this.#label = label;
    const components = new Map<string, ComponentType<Props>>();
    for (const definition of definitions) {
      if (components.has(definition.id)) {
        throw new Error(`Duplicate ${label} registration: ${definition.id}`);
      }
      components.set(definition.id, definition.component);
    }
    if (components.size === 0) throw new Error(`${label} registry cannot be empty.`);
    this.#components = components;
  }

  resolve(id: string): ComponentType<Props> {
    const component = this.#components.get(id);
    if (!component) throw new Error(`${this.#label} is not registered: ${id}`);
    return component;
  }

  has(id: string): boolean {
    return this.#components.has(id);
  }
}

class ValueRegistry<Value> {
  readonly #values: ReadonlyMap<string, Value>;
  readonly #label: string;

  constructor(
    label: string,
    definitions: readonly Readonly<{id: string; value: Value}>[],
  ) {
    this.#label = label;
    const values = new Map<string, Value>();
    for (const definition of definitions) {
      if (values.has(definition.id)) {
        throw new Error(`Duplicate ${label} registration: ${definition.id}`);
      }
      values.set(definition.id, definition.value);
    }
    if (values.size === 0) throw new Error(`${label} registry cannot be empty.`);
    this.#values = values;
  }

  resolve(id: string): Value {
    const value = this.#values.get(id);
    if (!value) throw new Error(`${this.#label} is not registered: ${id}`);
    return value;
  }

  has(id: string): boolean {
    return this.#values.has(id);
  }
}

const WorldWarmthIntro = (props: IntroRendererProps) => <TitleCard {...props} />;
const WorldWarmthOutro = (props: OutroRendererProps) => <ClosingCard {...props} />;
const SoftEditorialTransition = ({
  track,
  theme,
}: TransitionRendererProps) => (
  <TransitionScene
    type={track.transition_type}
    theme={theme}
    durationInFrames={track.durationInFrames}
  />
);

export const introRegistry = new ComponentRegistry<IntroRendererProps>('intro variant', [
  {id: 'world_warmth_intro', component: WorldWarmthIntro},
]);
export const outroRegistry = new ComponentRegistry<OutroRendererProps>('outro variant', [
  {id: 'world_warmth_outro', component: WorldWarmthOutro},
]);
export const transitionRegistry = new ComponentRegistry<TransitionRendererProps>(
  'transition pack',
  [{id: 'soft_editorial', component: SoftEditorialTransition}],
);

export type CaptionPreset = Readonly<{
  preferTranslation: boolean;
  maximumLines: number;
}>;
export type SourceBarPreset = Readonly<{
  prefix: string;
  showUrl: boolean;
}>;
export type HostPreset = Readonly<{
  objectFit: 'contain' | 'cover';
  enterFrames: number;
  exitFrames: number;
  enterOffsetPercent: number;
  enterScale: number;
}>;

export const captionPresetRegistry = new ValueRegistry<CaptionPreset>('caption preset', [
  {
    id: 'bilingual_editorial',
    value: {preferTranslation: true, maximumLines: 3},
  },
]);
export const sourceBarPresetRegistry = new ValueRegistry<SourceBarPreset>(
  'source bar preset',
  [{id: 'verified_source', value: {prefix: 'VERIFIED SOURCE', showUrl: false}}],
);
export const hostPresetRegistry = new ValueRegistry<HostPreset>('host preset', [
  {
    id: 'restrained_presenter',
    value: {
      objectFit: 'contain',
      enterFrames: 12,
      exitFrames: 12,
      enterOffsetPercent: 3,
      enterScale: 0.97,
    },
  },
]);

export const resolveProgramPresentation = (props: GodNewsVideoProps) => {
  const template = props.template;
  if (!template) throw new Error('Versioned template snapshot is required.');
  return {
    Intro: introRegistry.resolve(template.intro_variant),
    Outro: outroRegistry.resolve(template.outro_variant),
    Transition: transitionRegistry.resolve(template.transition_pack),
    captionPreset: captionPresetRegistry.resolve(template.caption_preset),
    sourceBarPreset: sourceBarPresetRegistry.resolve(template.source_bar_preset),
    hostPreset: hostPresetRegistry.resolve(template.host_preset),
  };
};
