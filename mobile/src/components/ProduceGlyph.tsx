import Svg, { Circle, Path } from 'react-native-svg';

/**
 * Simple drawings, made for this project, of common produce the icon set has no symbol for. Each is drawn in a
 * 48-unit box in one colour; `background` is the tile colour, used for the few lines drawn "into" a shape.
 */
export type ProduceGlyphName = 'onion' | 'potato' | 'brinjal' | 'cauliflower' | 'okra' | 'banana';

const GLYPH_BY_NAME: [RegExp, ProduceGlyphName][] = [
  [/onion|shallot|garlic/, 'onion'],
  [/potato/, 'potato'],
  [/brinjal|eggplant|aubergine/, 'brinjal'],
  [/cauliflower|broccoli/, 'cauliflower'],
  [/lady'?s finger|okra|bhindi/, 'okra'],
  [/banana|plantain/, 'banana'],
];

/** The drawing that fits a product's name, if there is one. */
export function produceGlyphFor(name: string): ProduceGlyphName | null {
  const lowered = name.toLowerCase();
  if (lowered.includes('spring onion')) return null; // a leafy bunch, not a bulb
  return GLYPH_BY_NAME.find(([pattern]) => pattern.test(lowered))?.[1] ?? null;
}

interface ProduceGlyphProps {
  name: ProduceGlyphName;
  size: number;
  color: string;
  background: string;
}

export function ProduceGlyph({ name, size, color, background }: ProduceGlyphProps) {
  const line = { stroke: background, strokeWidth: 1.6, strokeLinecap: 'round' as const, fill: 'none' };
  const stem = { stroke: color, strokeWidth: 3, strokeLinecap: 'round' as const, fill: 'none' };

  return (
    <Svg width={size} height={size} viewBox="0 0 48 48">
      {name === 'onion' ? (
        <>
          <Path d="M24 11C22 16 11 19 11 29c0 8 6 12 13 12s13-4 13-12c0-10-11-13-13-18Z" fill={color} />
          <Path d="M24 12 21 5M24 12l3-7" {...stem} strokeWidth={2.4} />
          <Path d="M24 17c-4 5-5 12-3 20M24 17c4 5 5 12 3 20" {...line} />
        </>
      ) : null}
      {name === 'potato' ? (
        <>
          <Path d="M15 18c3-8 15-10 21-3 6 7 4 19-5 23-9 4-19-1-21-9-1-4 3-7 5-11Z" fill={color} />
          <Circle cx={20} cy={24} r={1.5} fill={background} />
          <Circle cx={29} cy={20} r={1.5} fill={background} />
          <Circle cx={27} cy={31} r={1.5} fill={background} />
          <Circle cx={18} cy={32} r={1.2} fill={background} />
        </>
      ) : null}
      {name === 'brinjal' ? (
        <>
          <Path d="M31 15c8 6 7 20-3 25-10 5-19-3-16-13 2-8 12-15 19-12Z" fill={color} />
          <Path d="M36 12 40 7" {...stem} />
          <Path d="M26 14c3 2 7 2 10 6 1-4 2-6 0-8-2-2-6-1-10 2Z" fill={color} stroke={background} strokeWidth={1.4} />
        </>
      ) : null}
      {name === 'cauliflower' ? (
        <>
          <Path d="M7 25c1 11 8 17 17 17s16-6 17-17c-4 6-10 9-17 9S11 31 7 25Z" fill={color} opacity={0.55} />
          <Circle cx={17} cy={22} r={7} fill={color} />
          <Circle cx={26} cy={17} r={8} fill={color} />
          <Circle cx={33} cy={24} r={6.5} fill={color} />
          <Circle cx={24} cy={27} r={7.5} fill={color} />
          <Path d="M20 20c2-1 4-1 5 1M28 24c2-1 3 0 4 1" {...line} />
        </>
      ) : null}
      {name === 'okra' ? (
        <>
          <Path d="M10 39c-3-3 9-22 24-29 3-1 5 1 4 4-7 15-25 28-28 25Z" fill={color} />
          <Path d="M35 11 40 6" {...stem} />
          <Path d="M14 35c6-6 13-14 20-21" {...line} />
        </>
      ) : null}
      {name === 'banana' ? (
        <>
          <Path d="M9 13c2 13 13 22 30 19 1 3 0 5-3 6-16 4-30-6-31-23 0-2 2-4 5-2Z" fill={color} />
          <Path d="M9 13 7 8" {...stem} />
          <Path d="M10 20c4 9 13 15 25 14" {...line} />
        </>
      ) : null}
    </Svg>
  );
}
