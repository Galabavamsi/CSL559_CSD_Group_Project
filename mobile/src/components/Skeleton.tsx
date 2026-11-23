import { useEffect, useState } from 'react';
import { Animated, Platform, StyleSheet, View, type DimensionValue, type StyleProp, type ViewStyle } from 'react-native';

import { radius, space, useAppTheme } from '@/theme';

interface SkeletonProps {
  width?: DimensionValue;
  height: DimensionValue;
  rounded?: number;
  style?: StyleProp<ViewStyle>;
}

/** A grey block that pulses while the real content loads. It takes the size the content will take. */
export function Skeleton({ width = '100%', height, rounded = radius.sm, style }: SkeletonProps) {
  const { colors } = useAppTheme();
  const [opacity] = useState(() => new Animated.Value(0.55));

  useEffect(() => {
    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 1, duration: 700, useNativeDriver: Platform.OS !== 'web' }),
        Animated.timing(opacity, { toValue: 0.55, duration: 700, useNativeDriver: Platform.OS !== 'web' }),
      ]),
    );
    pulse.start();
    return () => pulse.stop();
  }, [opacity]);

  return (
    <Animated.View
      style={[{ width, height, borderRadius: rounded, backgroundColor: colors.surfaceVariant, opacity }, style]}
    />
  );
}

/** Stand-in for one product card of the home grid. */
export function ProductCardSkeleton() {
  const { colors } = useAppTheme();
  return (
    <View style={[styles.card, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
      <Skeleton height={104} rounded={radius.md} />
      <Skeleton height={16} width="80%" style={styles.gap} />
      <Skeleton height={12} width="55%" style={styles.gapSmall} />
      <Skeleton height={12} width="70%" style={styles.gapSmall} />
      <Skeleton height={40} rounded={radius.md} style={styles.gap} />
    </View>
  );
}

/** Stand-in for a row of a list (an order, a cart line). */
export function RowSkeleton() {
  const { colors } = useAppTheme();
  return (
    <View style={[styles.row, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
      <Skeleton width={56} height={56} rounded={radius.md} />
      <View style={styles.rowText}>
        <Skeleton height={16} width="70%" />
        <Skeleton height={12} width="45%" style={styles.gapSmall} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: space.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: space.md,
  },
  rowText: { flex: 1 },
  gap: { marginTop: space.md },
  gapSmall: { marginTop: space.sm },
});
