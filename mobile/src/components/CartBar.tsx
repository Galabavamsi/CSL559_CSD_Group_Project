import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { useCartSummary } from '@/features/cart/useCartActions';
import { formatRupees } from '@/lib/format';
import { MAX_CONTENT_WIDTH, radius, space, tabularNumbers, useAppTheme } from '@/theme';

/** Height the bar takes, for the bottom padding of the list it floats over. */
export const CART_BAR_SPACE = 80;

/**
 * Floats over the bottom of a shopping screen once the cart has something in it. Being an overlay, it does
 * not move the content when it appears; the screen always leaves CART_BAR_SPACE free for it.
 */
export function CartBar({ bottomInset = 0 }: { bottomInset?: number }) {
  const router = useRouter();
  const { colors } = useAppTheme();
  const { count, bill } = useCartSummary();

  if (count === 0) return null;
  const items = `${count} ${count === 1 ? 'item' : 'items'}`;

  return (
    <View style={[styles.wrap, { bottom: space.md + bottomInset }]} pointerEvents="box-none">
      <Pressable
        onPress={() => router.push('/cart')}
        accessibilityRole="button"
        accessibilityLabel={`View cart, ${items}${bill ? `, ${formatRupees(bill.total)}` : ''}`}
        style={({ pressed }) => [styles.bar, { backgroundColor: colors.primary }, pressed && styles.pressed]}>
        <View style={[styles.basket, { backgroundColor: colors.onPrimary }]}>
          <MaterialCommunityIcons name="basket" size={20} color={colors.primary} />
        </View>
        <View style={styles.summary}>
          <Text variant="labelMedium" style={[tabularNumbers, { color: colors.onPrimary }]}>
            {items}
          </Text>
          <Text variant="titleMedium" style={[tabularNumbers, { color: colors.onPrimary }]}>
            {bill ? formatRupees(bill.total) : ' '}
          </Text>
        </View>
        <Text variant="labelLarge" style={{ color: colors.onPrimary }}>
          View cart
        </Text>
        <MaterialCommunityIcons name="chevron-right" size={22} color={colors.onPrimary} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'absolute',
    left: space.lg,
    right: space.lg,
    alignItems: 'center',
  },
  bar: {
    width: '100%',
    maxWidth: MAX_CONTENT_WIDTH - space.lg * 2,
    minHeight: 56,
    borderRadius: radius.lg,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: space.md,
    gap: space.sm,
    boxShadow: '0px 4px 12px rgba(0, 0, 0, 0.25)',
  },
  pressed: { opacity: 0.9 },
  basket: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  summary: { flex: 1 },
});
