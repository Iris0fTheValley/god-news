import type {TimelineSegment} from '../schema';
import {captionPresetRegistry} from '../templates/presentation-registry';
import {AdaptiveCaptionText} from './AdaptiveCaptionText';

export const CaptionRenderer = ({
  segment,
  fontSize,
  maxLines,
  color,
  fontFamily,
  fontWeight,
  lineHeight,
  presetId,
  charactersPerLine,
}: {
  segment: TimelineSegment;
  fontSize: number;
  maxLines: number;
  color: string;
  fontFamily: string;
  fontWeight: number;
  lineHeight: number;
  presetId: string;
  charactersPerLine: number;
}) => {
  const preset = captionPresetRegistry.resolve(presetId);
  const text =
    (preset.preferTranslation
      ? segment.captions.find((caption) => caption.kind === 'translation')?.text
      : segment.captions.find((caption) => caption.kind === 'verbatim')?.text) ??
    segment.spoken_text;
  return (
    <AdaptiveCaptionText
      text={text}
      baseFontSize={fontSize}
      charactersPerLine={charactersPerLine}
      maxLines={Math.min(maxLines, preset.maximumLines)}
      color={color}
      fontFamily={fontFamily}
      fontWeight={fontWeight}
      lineHeight={lineHeight}
    />
  );
};
