import type { ComponentProps } from 'react';
import { TextInput } from 'react-native-paper';

import { useAppTheme } from '@/theme';

/**
 * The outlined Material text field, filled with the card colour. Every form in the app sits on a card, and the
 * library's default fill is the page colour, which would show as a tinted box there.
 */
export function TextField({ style, ...props }: ComponentProps<typeof TextInput>) {
  const { colors } = useAppTheme();
  return <TextInput mode="outlined" {...props} style={[{ backgroundColor: colors.elevation.level1 }, style]} />;
}

TextField.Icon = TextInput.Icon;
TextField.Affix = TextInput.Affix;
