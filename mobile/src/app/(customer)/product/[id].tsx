import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import type { ComponentProps, ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Product } from '@/api';
import { useProducts } from '@/api/queries';
import { DealBadge, GradeBadge } from '@/components/Badges';
import { Button } from '@/components/Button';
import { CART_BAR_SPACE, CartBar } from '@/components/CartBar';
import { ProductArt } from '@/components/ProductArt';
import { ProductCard } from '@/components/ProductCard';
import { QuantityStepper } from '@/components/QuantityStepper';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { TopBar } from '@/components/TopBar';
import { useSetCartQuantity } from '@/features/cart/useCartActions';
import { GRADE_EXPLANATION, pickedLabel, useByLabel } from '@/features/catalogue/freshness';
import { discountPercent, isRescueDeal, unitPrice } from '@/lib/bill';
import { formatRupees } from '@/lib/format';
import { useCart } from '@/state/cart';
import { useDeliveryLocation } from '@/state/deliveryLocation';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

const SIMILAR_LIMIT = 8;
const SIMILAR_CARD_WIDTH = 156;

export default function ProductDetail() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const { id } = useLocalSearchParams<{ id: string }>();

  const location = useDeliveryLocation((state) => state.location);
  const hubId = location?.hubId ?? null;
  const products = useProducts(hubId);
  const cartHubId = useCart((state) => state.hubId);
  const cartQuantities = useCart((state) => state.quantities);
  const quantityOf = (productId: number) => (cartHubId === hubId ? (cartQuantities[productId] ?? 0) : 0);
  const setQuantity = useSetCartQuantity();

  const product = products.data?.find((candidate) => String(candidate.id) === id);
  const openProduct = (other: Product) => router.push({ pathname: '/product/[id]', params: { id: other.id } });

  let body: ReactNode;
  if (products.data === undefined && !products.isError) {
    body = (
      <View style={styles.content}>
        <Skeleton height={220} rounded={radius.xl} />
        <Skeleton height={28} width="60%" style={styles.gapLarge} />
        <Skeleton height={16} width="40%" style={styles.gap} />
        <Skeleton height={48} style={styles.gapLarge} />
        <Skeleton height={96} rounded={radius.lg} style={styles.gapLarge} />
      </View>
    );
  } else if (products.data === undefined) {
    body = <ErrorState error={products.error} onRetry={() => products.refetch()} retrying={products.isRefetching} />;
  } else if (!product) {
    body = (
      <EmptyState
        icon="basket-off-outline"
        title="No longer listed"
        message="Your hub is not offering this item at the moment.">
        <Button mode="contained" onPress={() => router.replace('/home')}>
          Back to the shop
        </Button>
      </EmptyState>
    );
  } else {
    const deal = isRescueDeal(product);
    const soldOut = product.available <= 0;
    const picked = pickedLabel(product.harvestDate);
    const useBy = useByLabel(product.useByDate);
    const similar = (products.data ?? [])
      .filter((other) => other.category === product.category && other.id !== product.id)
      .sort((a, b) => Number(b.available > 0) - Number(a.available > 0))
      .slice(0, SIMILAR_LIMIT);

    body = (
      <ScrollView contentContainerStyle={[styles.content, { paddingBottom: CART_BAR_SPACE + insets.bottom + space.lg }]}>
        <View>
          <ProductArt
            name={product.name}
            category={product.category}
            imageUrl={product.imageUrl}
            iconSize={120}
            dimmed={soldOut}
            style={styles.art}
          />
          <View style={styles.badges} pointerEvents="none">
            {product.grade ? <GradeBadge grade={product.grade} /> : <View />}
            {deal ? <DealBadge percent={discountPercent(product)} /> : null}
          </View>
        </View>

        <Text variant="headlineSmall" style={styles.gapLarge}>
          {product.name}
        </Text>
        {product.unitLabel ? (
          <Text variant="bodyLarge" style={{ color: colors.onSurfaceVariant }}>
            {product.unitLabel}
          </Text>
        ) : null}

        <View style={styles.buyRow}>
          <View style={styles.flex}>
            <View style={styles.priceRow}>
              <Text variant="headlineSmall" style={tabularNumbers}>
                {formatRupees(unitPrice(product))}
              </Text>
              {deal ? (
                <Text variant="bodyMedium" style={[styles.wasPrice, tabularNumbers, { color: colors.onSurfaceVariant }]}>
                  {formatRupees(product.price)}
                </Text>
              ) : null}
            </View>
            <Text variant="bodySmall" style={{ color: deal ? colors.tertiary : colors.onSurfaceVariant }}>
              {deal
                ? product.markdownUnits !== null
                  ? `Rescue deal, last day of freshness: ${product.markdownUnits} at this price`
                  : 'Rescue deal: last day of freshness'
                : 'Price for one unit'}
            </Text>
          </View>
          <View style={styles.stepper}>
            <QuantityStepper
              itemName={product.name}
              quantity={quantityOf(product.id)}
              max={product.available}
              onChange={(quantity) => setQuantity(product.id, quantity)}
            />
          </View>
        </View>

        {picked || useBy ? (
          <InfoCard icon="calendar-clock" title="Freshness">
            {[picked, useBy].filter(Boolean).join(' · ')}
          </InfoCard>
        ) : null}
        {product.farmName ? (
          <InfoCard icon="barn" title={product.farmName}>
            {`Dropped off at ${location?.hubName ?? 'your hub'}, where it was graded and packed.`}
          </InfoCard>
        ) : null}
        {product.grade ? (
          <InfoCard icon="check-decagram" title={GRADE_EXPLANATION[product.grade].title}>
            {GRADE_EXPLANATION[product.grade].body}
          </InfoCard>
        ) : null}

        {similar.length > 0 ? (
          <>
            <Text variant="titleMedium" style={styles.similarTitle}>
              Similar items
            </Text>
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.similarStrip}
              style={styles.bleed}>
              {similar.map((other) => (
                <ProductCard
                  key={other.id}
                  product={other}
                  quantity={quantityOf(other.id)}
                  onChangeQuantity={(quantity) => setQuantity(other.id, quantity)}
                  onOpen={() => openProduct(other)}
                  style={styles.similarCard}
                />
              ))}
            </ScrollView>
          </>
        ) : null}
      </ScrollView>
    );
  }

  return (
    <Screen>
      <TopBar title="Details" backFallback="/home" />
      {body}
      <CartBar bottomInset={insets.bottom} />
    </Screen>
  );
}

function InfoCard({ icon, title, children }: { icon: IconName; title: string; children: string }) {
  const { colors } = useAppTheme();
  return (
    <View style={[styles.info, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
      <View style={[styles.infoIcon, { backgroundColor: colors.primaryContainer }]}>
        <MaterialCommunityIcons name={icon} size={20} color={colors.onPrimaryContainer} />
      </View>
      <View style={styles.flex}>
        <Text variant="titleSmall">{title}</Text>
        <Text variant="bodyMedium" style={{ color: colors.onSurfaceVariant }}>
          {children}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { paddingHorizontal: space.lg, paddingTop: space.sm },
  gap: { marginTop: space.sm },
  gapLarge: { marginTop: space.lg },
  art: { height: 220, borderRadius: radius.xl },
  badges: {
    position: 'absolute',
    top: space.md,
    left: space.md,
    right: space.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  buyRow: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginTop: space.md, marginBottom: space.sm },
  priceRow: { flexDirection: 'row', alignItems: 'baseline', gap: space.sm },
  wasPrice: { textDecorationLine: 'line-through' },
  stepper: { width: 136 },
  info: {
    marginTop: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: space.md,
    flexDirection: 'row',
    gap: space.md,
  },
  infoIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  similarTitle: { marginTop: space.xl, marginBottom: space.md },
  bleed: { marginHorizontal: -space.lg },
  similarStrip: { paddingHorizontal: space.lg, gap: space.md },
  similarCard: { width: SIMILAR_CARD_WIDTH },
});
