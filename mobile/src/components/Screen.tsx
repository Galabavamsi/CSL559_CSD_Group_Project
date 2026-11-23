import type { ReactNode } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { MAX_CONTENT_WIDTH, useAppTheme } from '@/theme';

interface ScreenProps {
  children: ReactNode;
  /** Pad the top for the status bar. Leave off when the screen starts with a TopBar, which pads itself. */
  padTop?: boolean;
  style?: StyleProp<ViewStyle>;
}

/**
 * The frame of every screen: page background, side insets (a phone held sideways, a notch), and a column that
 * stays phone-wide on a large web window.
 */
export function Screen({ children, padTop = false, style }: ScreenProps) {
  const { colors } = useAppTheme();
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.page,
        { backgroundColor: colors.background, paddingLeft: insets.left, paddingRight: insets.right },
        padTop && { paddingTop: insets.top },
      ]}>
      <View style={[styles.column, style]}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, alignItems: 'center' },
  column: { flex: 1, width: '100%', maxWidth: MAX_CONTENT_WIDTH },
});
