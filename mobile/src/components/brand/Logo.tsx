import Svg, { Path } from 'react-native-svg';

import { useAppTheme } from '@/theme';

import paths from './logo-paths.json';

interface LogoProps {
  size?: number;
  /** "brand" sits on the page background; "inverse" sits on the primary colour. */
  tone?: 'brand' | 'inverse';
}

/**
 * The Farm2Home mark: a map pin (your address) holding a house (home) with a leaf at its door (the farm).
 * Drawn for this project. The shapes live in logo-paths.json, which scripts/make-icons.mjs also reads to draw
 * the app icon, so the icon and the in-app logo cannot drift apart.
 */
export function Logo({ size = 48, tone = 'brand' }: LogoProps) {
  const { colors } = useAppTheme();
  const pin = tone === 'brand' ? colors.primary : colors.onPrimary;
  const house = tone === 'brand' ? colors.onPrimary : colors.primary;

  return (
    <Svg
      width={size}
      height={size}
      viewBox={`0 0 ${paths.viewBox} ${paths.viewBox}`}
      accessibilityRole="image"
      accessibilityLabel="Farm2Home logo">
      <Path d={paths.pin} fill={pin} />
      <Path d={paths.house} fill={house} />
      <Path d={paths.leaf} fill={pin} />
      <Path d={paths.midrib} fill={house} />
    </Svg>
  );
}
