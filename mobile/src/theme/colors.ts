/**
 * Colour roles for the two themes. The names follow Material Design 3; the values are our own:
 * a fresh leaf green, a tomato accent with a mango highlight, and warm paper-like neutrals.
 */
import type { MD3Theme } from 'react-native-paper';

type MD3Colors = MD3Theme['colors'];

/** A soft background with an icon colour that reads on it. Used for product art and status marks. */
export interface Tint {
  background: string;
  foreground: string;
}

/** Colours Material Design has no role for. */
export interface BrandColors {
  /** Mango: highlights that are neither an action nor a warning (Grade B, time running low). */
  mango: string;
  onMango: string;
  mangoContainer: string;
  onMangoContainer: string;
  /** Product art tiles, by category. */
  tiles: {
    vegetables: Tint;
    leafyGreens: Tint;
    fruits: Tint;
    herbs: Tint;
    other: Tint;
  };
}

export const lightColors: MD3Colors = {
  primary: '#2A8540',
  onPrimary: '#FFFFFF',
  primaryContainer: '#CBEFC6',
  onPrimaryContainer: '#06210E',
  secondary: '#55634F',
  onSecondary: '#FFFFFF',
  secondaryContainer: '#DDEBD2',
  onSecondaryContainer: '#141E10',
  tertiary: '#C7402A',
  onTertiary: '#FFFFFF',
  tertiaryContainer: '#FFDAD2',
  onTertiaryContainer: '#3F0700',
  error: '#BA1A1A',
  onError: '#FFFFFF',
  errorContainer: '#FFDAD6',
  onErrorContainer: '#410002',
  background: '#FBF7F0',
  onBackground: '#1F1B16',
  surface: '#FFFCF7',
  onSurface: '#1F1B16',
  surfaceVariant: '#EEE7DB',
  onSurfaceVariant: '#4F473C',
  outline: '#82796B',
  outlineVariant: '#D8CFC0',
  shadow: '#000000',
  scrim: '#000000',
  inverseSurface: '#352F29',
  inverseOnSurface: '#FAEFE4',
  inversePrimary: '#8FD98A',
  surfaceDisabled: 'rgba(31, 27, 22, 0.12)',
  onSurfaceDisabled: 'rgba(31, 27, 22, 0.38)',
  backdrop: 'rgba(56, 48, 38, 0.45)',
  elevation: {
    level0: 'transparent',
    level1: '#FFFFFF',
    level2: '#FFFDF9',
    level3: '#F6F0E6',
    level4: '#F3ECE1',
    level5: '#EFE8DB',
  },
};

export const darkColors: MD3Colors = {
  primary: '#8FD98A',
  onPrimary: '#00390F',
  primaryContainer: '#145224',
  onPrimaryContainer: '#ABF5A4',
  secondary: '#BCCBB3',
  onSecondary: '#273422',
  secondaryContainer: '#3D4B37',
  onSecondaryContainer: '#D8E7CE',
  tertiary: '#FFB4A3',
  onTertiary: '#640F02',
  tertiaryContainer: '#8A2414',
  onTertiaryContainer: '#FFDAD2',
  error: '#FFB4AB',
  onError: '#690005',
  errorContainer: '#93000A',
  onErrorContainer: '#FFDAD6',
  background: '#151310',
  onBackground: '#EBE1D5',
  surface: '#1B1915',
  onSurface: '#EBE1D5',
  surfaceVariant: '#3A352D',
  onSurfaceVariant: '#D2C5B4',
  outline: '#9B8F80',
  outlineVariant: '#4D463B',
  shadow: '#000000',
  scrim: '#000000',
  inverseSurface: '#EBE1D5',
  inverseOnSurface: '#352F29',
  inversePrimary: '#2A8540',
  surfaceDisabled: 'rgba(235, 225, 213, 0.12)',
  onSurfaceDisabled: 'rgba(235, 225, 213, 0.38)',
  backdrop: 'rgba(10, 8, 6, 0.6)',
  elevation: {
    level0: 'transparent',
    level1: '#221F1A',
    level2: '#27241E',
    level3: '#2D2922',
    level4: '#2F2B24',
    level5: '#343028',
  },
};

export const lightBrand: BrandColors = {
  mango: '#F2A31B',
  onMango: '#3B2500',
  mangoContainer: '#FFE7B8',
  onMangoContainer: '#3B2500',
  tiles: {
    vegetables: { background: '#FFE3DA', foreground: '#C7402A' },
    leafyGreens: { background: '#D5F0CE', foreground: '#2A8540' },
    fruits: { background: '#FFE9BE', foreground: '#A86400' },
    herbs: { background: '#E5F1C6', foreground: '#5B7512' },
    other: { background: '#EEE7DB', foreground: '#4F473C' },
  },
};

export const darkBrand: BrandColors = {
  mango: '#FFC55C',
  onMango: '#422C00',
  mangoContainer: '#5E4100',
  onMangoContainer: '#FFDEA6',
  tiles: {
    vegetables: { background: '#4A2219', foreground: '#FFB4A3' },
    leafyGreens: { background: '#1D3F23', foreground: '#8FD98A' },
    fruits: { background: '#4A3610', foreground: '#FFC55C' },
    herbs: { background: '#33401A', foreground: '#C5DC84' },
    other: { background: '#3A352D', foreground: '#D2C5B4' },
  },
};
