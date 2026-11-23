import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import { Text } from 'react-native-paper';

import type { Product } from '@/api';
import { pickedLabel, useByLabel } from '@/features/catalogue/freshness';
import { discountPercent, isRescueDeal, unitPrice } from '@/lib/bill';
import { formatRupees } from '@/lib/format';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';

import { DealBadge, GradeBadge } from './Badges';
import { ProductArt } from './ProductArt';
import { QuantityStepper } from './QuantityStepper';

interface ProductCardProps {
  product: Product;
  quantity: number;
  onChangeQuantity: (quantity: number) => void;
  onOpen: () => void;
  style?: StyleProp<ViewStyle>;
}

/** How few units count as "nearly gone" and get a note on the card. */
const LOW_STOCK = 3;

/** One sellable unit in the grid or the deals strip: art, what it is, how fresh, what it costs, and the stepper. */
export function ProductCard({ product, quantity, onChangeQuantity, onOpen, style }: ProductCardProps) {
  const { colors } = useAppTheme();
  const deal = isRescueDeal(product);
  const soldOut = product.available <= 0;
  const picked = pickedLabel(product.harvestDate);
  const useBy = useByLabel(product.useByDate);
  const price = formatRupees(unitPrice(product));

  return (
    <View style={[styles.card, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }, style]}>
      <Pressable
        onPress={onOpen}
        accessibilityRole="button"
        accessibilityLabel={[product.name, product.unitLabel, price, soldOut ? 'out of stock' : null]
          .filter(Boolean)
          .join(', ')}
        accessibilityHint="Opens the details"
        style={({ pressed }) => [styles.body, pressed && styles.pressed]}>
        <View>
          <ProductArt
            name={product.name}
            category={product.category}
            imageUrl={product.imageUrl}
            dimmed={soldOut}
            style={styles.art}
          />
          <View style={styles.badges} pointerEvents="none">
            {product.grade ? <GradeBadge grade={product.grade} /> : <View />}
            {deal ? <DealBadge percent={discountPercent(product)} /> : null}
          </View>
        </View>

        <Text variant="titleSmall" numberOfLines={2} style={styles.name}>
          {product.name}
        </Text>
        {product.unitLabel ? (
          <Text variant="bodySmall" numberOfLines={1} style={{ color: colors.onSurfaceVariant }}>
            {product.unitLabel}
          </Text>
        ) : null}
        {picked ? (
          <Text variant="bodySmall" numberOfLines={1} style={[styles.freshness, { color: colors.primary }]}>
            {picked}
          </Text>
        ) : null}
        {useBy ? (
          <Text variant="bodySmall" numberOfLines={1} style={{ color: deal ? colors.tertiary : colors.onSurfaceVariant }}>
            {useBy}
          </Text>
        ) : null}
        {!soldOut && product.available <= LOW_STOCK ? (
          <Text variant="labelSmall" style={[styles.freshness, { color: colors.tertiary }]}>
            Only {product.available} left
          </Text>
        ) : null}

        <View style={styles.priceRow}>
          <Text variant="titleMedium" style={tabularNumbers}>
            {price}
          </Text>
          {deal ? (
            <Text variant="bodySmall" style={[styles.wasPrice, tabularNumbers, { color: colors.onSurfaceVariant }]}>
              {formatRupees(product.price)}
            </Text>
          ) : null}
        </View>
      </Pressable>

      <QuantityStepper
        itemName={product.name}
        quantity={quantity}
        max={product.available}
        onChange={onChangeQuantity}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.sm,
    paddingTop: space.sm,
    paddingBottom: space.xs,
  },
  body: { flexGrow: 1 },
  pressed: { opacity: 0.7 },
  art: { height: 104 },
  badges: {
    position: 'absolute',
    top: 6,
    left: 6,
    right: 6,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  name: { marginTop: space.sm },
  freshness: { marginTop: 2 },
  priceRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 6,
    marginTop: 'auto',
    paddingTop: space.sm,
  },
  wasPrice: { textDecorationLine: 'line-through' },
});
