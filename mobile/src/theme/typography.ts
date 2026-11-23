/**
 * Type scale. Every style names its font file directly and keeps `fontWeight` at 400: the weight lives in the
 * file, and asking the platform for bold on top would smear it (Android and the web both fake a bolder face).
 */
import { PlusJakartaSans_400Regular } from '@expo-google-fonts/plus-jakarta-sans/400Regular';
import { PlusJakartaSans_500Medium } from '@expo-google-fonts/plus-jakarta-sans/500Medium';
import { PlusJakartaSans_600SemiBold } from '@expo-google-fonts/plus-jakarta-sans/600SemiBold';
import { PlusJakartaSans_700Bold } from '@expo-google-fonts/plus-jakarta-sans/700Bold';
import { PlusJakartaSans_800ExtraBold } from '@expo-google-fonts/plus-jakarta-sans/800ExtraBold';
import { configureFonts } from 'react-native-paper';

/** Passed to `useFonts` once, at start-up. */
export const fontAssets = {
  PlusJakartaSans_400Regular,
  PlusJakartaSans_500Medium,
  PlusJakartaSans_600SemiBold,
  PlusJakartaSans_700Bold,
  PlusJakartaSans_800ExtraBold,
};

export const fontFamily = {
  regular: 'PlusJakartaSans_400Regular',
  medium: 'PlusJakartaSans_500Medium',
  semiBold: 'PlusJakartaSans_600SemiBold',
  bold: 'PlusJakartaSans_700Bold',
  extraBold: 'PlusJakartaSans_800ExtraBold',
} as const;

function style(family: string, fontSize: number, lineHeight: number, letterSpacing = 0) {
  return { fontFamily: family, fontWeight: '400' as const, fontSize, lineHeight, letterSpacing };
}

export const fonts = {
  ...configureFonts({
    config: {
    displayLarge: style(fontFamily.extraBold, 48, 56, -0.5),
    displayMedium: style(fontFamily.extraBold, 40, 48, -0.5),
    displaySmall: style(fontFamily.extraBold, 34, 42, -0.4),
    headlineLarge: style(fontFamily.extraBold, 30, 38, -0.3),
    headlineMedium: style(fontFamily.bold, 26, 34, -0.2),
    headlineSmall: style(fontFamily.bold, 22, 30, -0.1),
    titleLarge: style(fontFamily.bold, 20, 28),
    titleMedium: style(fontFamily.semiBold, 16, 24),
    titleSmall: style(fontFamily.semiBold, 14, 20),
    labelLarge: style(fontFamily.semiBold, 14, 20, 0.1),
    labelMedium: style(fontFamily.semiBold, 12, 16, 0.2),
    labelSmall: style(fontFamily.semiBold, 11, 16, 0.3),
    bodyLarge: style(fontFamily.regular, 16, 24),
    bodyMedium: style(fontFamily.regular, 14, 20),
      bodySmall: style(fontFamily.regular, 12, 16),
    },
  }),
  default: { fontFamily: fontFamily.regular, fontWeight: '400' as const, letterSpacing: 0 },
};

/** Digits that all take the same width, so a number can change without the text around it moving. */
export const tabularNumbers = { fontVariant: ['tabular-nums' as const] };
