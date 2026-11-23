import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { Grade } from '@/api';
import { radius, useAppTheme } from '@/theme';

/** "Grade A" on leaf green, "Grade B" on mango. */
export function GradeBadge({ grade }: { grade: Grade }) {
  const { colors, brand } = useAppTheme();
  const background = grade === 'A' ? colors.primaryContainer : brand.mangoContainer;
  const foreground = grade === 'A' ? colors.onPrimaryContainer : brand.onMangoContainer;
  return (
    <View style={[styles.badge, { backgroundColor: background }]}>
      <Text variant="labelSmall" style={{ color: foreground }}>
        Grade {grade}
      </Text>
    </View>
  );
}

/** "30% off" on tomato, for a rescue deal. */
export function DealBadge({ percent }: { percent: number }) {
  const { colors } = useAppTheme();
  return (
    <View style={[styles.badge, { backgroundColor: colors.tertiary }]}>
      <Text variant="labelSmall" style={{ color: colors.onTertiary }}>
        {percent}% off
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    alignSelf: 'flex-start',
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
});
