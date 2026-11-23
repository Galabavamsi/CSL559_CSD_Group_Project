import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Pressable, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { radius, tabularNumbers, TOUCH_TARGET, useAppTheme } from '@/theme';

interface QuantityStepperProps {
  /** Named in the screen-reader labels: "Add Tomato to cart". */
  itemName: string;
  quantity: number;
  /** Units the hub can still sell; the plus button stops here. */
  max: number;
  onChange: (quantity: number) => void;
}

/** The painted control is 40 dp tall, centred in a 48 dp tall touch area. */
const VISUAL_INSET = (TOUCH_TARGET - 40) / 2;

/**
 * "Add" when the item is not in the cart, "− n +" when it is. Both states have the same size, and the count
 * has a fixed width, so nothing around the control moves when the number changes.
 */
export function QuantityStepper({ itemName, quantity, max, onChange }: QuantityStepperProps) {
  const { colors } = useAppTheme();

  if (max <= 0 && quantity === 0) {
    return (
      <View style={styles.touchArea} accessible accessibilityLabel={`${itemName} is out of stock`}>
        <View style={[styles.paint, { borderColor: colors.outlineVariant }]} />
        <Text variant="labelLarge" style={{ color: colors.onSurfaceDisabled }}>
          Out of stock
        </Text>
      </View>
    );
  }

  if (quantity === 0) {
    return (
      <Pressable
        onPress={() => onChange(1)}
        accessibilityRole="button"
        accessibilityLabel={`Add ${itemName} to cart`}
        style={[styles.touchArea, styles.labelled]}>
        {({ pressed }) => (
          <>
            <View
              style={[
                styles.paint,
                { borderColor: colors.primary, backgroundColor: pressed ? colors.primaryContainer : 'transparent' },
              ]}
            />
            <MaterialCommunityIcons name="plus" size={18} color={colors.primary} />
            <Text variant="labelLarge" style={{ color: colors.primary }}>
              Add
            </Text>
          </>
        )}
      </Pressable>
    );
  }

  const atMax = quantity >= max;
  return (
    <View style={styles.touchArea}>
      <View style={[styles.paint, { borderColor: colors.primary, backgroundColor: colors.primary }]} />
      <Pressable
        onPress={() => onChange(quantity - 1)}
        accessibilityRole="button"
        accessibilityLabel={quantity === 1 ? `Remove ${itemName} from cart` : `Remove one ${itemName}`}
        style={({ pressed }) => [styles.side, pressed && styles.pressed]}>
        <MaterialCommunityIcons name="minus" size={20} color={colors.onPrimary} />
      </Pressable>
      <Text
        variant="labelLarge"
        accessibilityLabel={`${quantity} in cart`}
        accessibilityLiveRegion="polite"
        style={[styles.count, tabularNumbers, { color: colors.onPrimary }]}>
        {quantity}
      </Text>
      <Pressable
        onPress={() => onChange(quantity + 1)}
        disabled={atMax}
        accessibilityRole="button"
        accessibilityLabel={atMax ? `No more ${itemName} in stock` : `Add one more ${itemName}`}
        accessibilityState={{ disabled: atMax }}
        style={({ pressed }) => [styles.side, pressed && styles.pressed, atMax && styles.disabled]}>
        <MaterialCommunityIcons name="plus" size={20} color={colors.onPrimary} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  touchArea: {
    height: TOUCH_TARGET,
    minWidth: 128,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
  },
  labelled: { gap: 4 },
  paint: {
    position: 'absolute',
    top: VISUAL_INSET,
    bottom: VISUAL_INSET,
    left: 0,
    right: 0,
    borderRadius: radius.md,
    borderWidth: 1,
  },
  side: { flex: 1, minWidth: TOUCH_TARGET, height: TOUCH_TARGET, alignItems: 'center', justifyContent: 'center' },
  count: { width: 32, textAlign: 'center' },
  pressed: { opacity: 0.6 },
  disabled: { opacity: 0.4 },
});
