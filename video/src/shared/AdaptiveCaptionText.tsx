const captionUnits = (text: string): number =>
  [...text].reduce((total, character) => {
    if (/\s/u.test(character)) return total + 0.25;
    if (/[\u0000-\u024f]/u.test(character)) return total + 0.55;
    return total + 1;
  }, 0);

export const captionFontScale = ({
  text,
  charactersPerLine,
  maxLines,
}: {
  text: string;
  charactersPerLine: number;
  maxLines: number;
}): number => {
  const units = captionUnits(text);
  const capacity = charactersPerLine * maxLines;
  if (units <= capacity) return 1;
  const requiredScale = capacity / units;
  if (requiredScale < 0.55) {
    throw new Error(
      `Caption exceeds renderable capacity (${Math.ceil(units)} weighted characters).`,
    );
  }
  return requiredScale;
};

export const AdaptiveCaptionText = ({
  text,
  baseFontSize,
  charactersPerLine,
  maxLines,
  color,
  fontFamily,
  fontWeight,
  lineHeight,
  style,
}: {
  text: string;
  baseFontSize: number;
  charactersPerLine: number;
  maxLines: number;
  color: string;
  fontFamily: string;
  fontWeight: number;
  lineHeight: number;
  style?: React.CSSProperties;
}) => {
  const scale = captionFontScale({text, charactersPerLine, maxLines});
  return (
    <div
      data-caption-region
      data-caption-font-scale={scale.toFixed(3)}
      style={{
        color,
        display: '-webkit-box',
        fontFamily,
        fontSize: Math.round(baseFontSize * scale),
        fontWeight,
        lineHeight,
        overflow: 'hidden',
        textAlign: 'center',
        textOverflow: 'ellipsis',
        WebkitBoxOrient: 'vertical',
        WebkitLineClamp: maxLines,
        ...style,
      }}
    >
      {text}
    </div>
  );
};
