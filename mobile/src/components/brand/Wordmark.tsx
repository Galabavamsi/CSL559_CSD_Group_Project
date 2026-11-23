import { Text } from 'react-native-paper';

import { fontFamily, useAppTheme } from '@/theme';

interface WordmarkProps {
  size?: number;
  tone?: 'brand' | 'inverse';
}

/** The product name set in type: "Farm" and "Home" joined by a tomato-red 2. */
export function Wordmark({ size = 28, tone = 'brand' }: WordmarkProps) {
  const { colors } = useAppTheme();
  const ink = tone === 'brand' ? colors.onBackground : colors.onPrimary;
  const leaf = tone === 'brand' ? colors.primary : colors.onPrimary;
  const accent = tone === 'brand' ? colors.tertiary : colors.primaryContainer;

  return (
    <Text
      accessibilityRole="header"
      accessibilityLabel="Farm2Home"
      style={{
        fontFamily: fontFamily.extraBold,
        fontSize: size,
        lineHeight: Math.round(size * 1.25),
        letterSpacing: -0.5,
        color: ink,
      }}>
      Farm<Text style={{ fontFamily: fontFamily.extraBold, color: accent }}>2</Text>
      <Text style={{ fontFamily: fontFamily.extraBold, color: leaf }}>Home</Text>
    </Text>
  );
}
