import { MD3DarkTheme, MD3LightTheme, useTheme, type MD3Theme } from 'react-native-paper';

import { darkBrand, darkColors, lightBrand, lightColors, type BrandColors } from './colors';
import { fonts } from './typography';

export type AppTheme = MD3Theme & { brand: BrandColors };

export const lightTheme: AppTheme = {
  ...MD3LightTheme,
  roundness: 4,
  colors: lightColors,
  fonts,
  brand: lightBrand,
};

export const darkTheme: AppTheme = {
  ...MD3DarkTheme,
  roundness: 4,
  colors: darkColors,
  fonts,
  brand: darkBrand,
};

export const useAppTheme = () => useTheme<AppTheme>();

/** Spacing steps in dp. */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;

/** Corner radii in dp. */
export const radius = { sm: 8, md: 12, lg: 16, xl: 24, pill: 999 } as const;

/** The smallest touch target (Material Design: 48 dp). */
export const TOUCH_TARGET = 48;

/** Content never grows wider than this, so the web build stays phone-shaped on a wide window. */
export const MAX_CONTENT_WIDTH = 560;

export { fontFamily, tabularNumbers } from './typography';
export type { BrandColors, Tint } from './colors';
