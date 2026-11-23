import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Pressable, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { IconName } from '@/features/catalogue/categories';
import { radius, TOUCH_TARGET, useAppTheme } from '@/theme';

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  icon?: IconName;
}

interface SegmentedProps<T extends string> {
  options: SegmentOption<T>[];
  /** null when nothing is chosen yet. */
  value: T | null;
  onChange: (value: T) => void;
  /** Says what is being chosen, for screen readers: "City". */
  accessibilityLabel: string;
}

/**
 * A row of two to four choices of which one is on (Material's segmented button). Every segment is 48 dp tall
 * and equally wide, and labels are kept short enough to fit three across a 360 dp phone.
 */
export function Segmented<T extends string>({ options, value, onChange, accessibilityLabel }: SegmentedProps<T>) {
  const { colors } = useAppTheme();
  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
      style={[styles.row, { borderColor: colors.outline }]}>
      {options.map((option, index) => {
        const selected = option.value === value;
        const ink = selected ? colors.onSecondaryContainer : colors.onSurface;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected }}
            accessibilityLabel={option.label}
            style={[
              styles.segment,
              index > 0 && { borderLeftWidth: 1, borderLeftColor: colors.outline },
              selected && { backgroundColor: colors.secondaryContainer },
            ]}>
            {option.icon ? <MaterialCommunityIcons name={option.icon} size={18} color={ink} /> : null}
            <Text variant="labelLarge" numberOfLines={1} style={{ color: ink }}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    borderWidth: 1,
    borderRadius: radius.pill,
    overflow: 'hidden',
  },
  segment: {
    flex: 1,
    minHeight: TOUCH_TARGET,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    paddingHorizontal: 6,
  },
});
