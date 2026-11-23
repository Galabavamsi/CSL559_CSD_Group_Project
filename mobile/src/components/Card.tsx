import type { ReactNode } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { Text } from 'react-native-paper';

import { radius, space, useAppTheme } from '@/theme';

interface CardProps {
  title?: string;
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}

/** A plain white (or raised dark) panel with a hairline edge: the container for every group of content. */
export function Card({ title, children, style }: CardProps) {
  const { colors } = useAppTheme();
  return (
    <View style={[styles.card, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }, style]}>
      {title ? (
        <Text variant="titleMedium" style={styles.title}>
          {title}
        </Text>
      ) : null}
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, padding: space.lg },
  title: { marginBottom: space.md },
});
