import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import { Divider, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, type Product } from '@/api';
import { useCreateHold, useProducts } from '@/api/queries';
import { BillSummary } from '@/components/BillSummary';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Clock } from '@/components/HoldCountdown';
import { ProductArt } from '@/components/ProductArt';
import { QuantityStepper } from '@/components/QuantityStepper';
import { Screen } from '@/components/Screen';
import { RowSkeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { TopBar } from '@/components/TopBar';
import { useSetCartQuantity } from '@/features/cart/useCartActions';
import { chargeFor, computeBill, unitPrice } from '@/lib/bill';
import { secondsUntil } from '@/lib/dates';
import { useNow } from '@/lib/hooks';
import { newOrderId } from '@/lib/ids';
import { formatRupees } from '@/lib/format';
import { cartLines, useCart } from '@/state/cart';
import { useDeliveryLocation } from '@/state/deliveryLocation';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';

export default function Cart() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, brand } = useAppTheme();
  const now = useNow();

  const location = useDeliveryLocation((state) => state.location);
  const hubId = location?.hubId ?? null;
  const products = useProducts(hubId);
  const cartHubId = useCart((state) => state.hubId);
  const quantities = useCart((state) => state.quantities);
  const hold = useCart((state) => state.hold);
  const setQuantity = useSetCartQuantity();
  const createHold = useCreateHold();

  // A hold whose time is up counts as no hold here. The checkout screen is the one that tells the customer.
  const holdSecondsLeft = hold ? secondsUntil(hold.expiresAt, now) : 0;
  const holding = hold !== null && holdSecondsLeft > 0;

  const lines = hubId !== null && cartHubId === hubId ? cartLines(quantities) : [];
  const productById = new Map((products.data ?? []).map((product) => [product.id, product]));
  const bill = computeBill(lines, products.data ?? []);
  const listedLines = lines.filter((line) => productById.has(line.productId));
  // While a hold runs, "available" already has this cart taken out of it, so it says nothing about this cart.
  const shortLines = holding
    ? []
    : lines.filter((line) => {
        const product = productById.get(line.productId);
        return product !== undefined && line.quantity > product.available;
      });
  const needsFixing = shortLines.length > 0 || bill.missingProductIds.length > 0;

  const fitCartToStock = () => {
    for (const line of shortLines) setQuantity(line.productId, productById.get(line.productId)?.available ?? 0);
    for (const productId of bill.missingProductIds) setQuantity(productId, 0);
    createHold.reset();
  };

  const holdItems = () => {
    if (hubId === null || !location) return;
    createHold.mutate(
      { orderId: newOrderId(), hubId, lines, h3Cell: location.h3Cell },
      { onSuccess: () => router.push('/checkout') },
    );
  };

  let body: ReactNode;
  if (lines.length === 0) {
    body = (
      <EmptyState
        icon="basket-outline"
        title="Your cart is empty"
        message="Add produce from your hub and it will wait for you here.">
        <Button mode="contained" onPress={() => router.replace('/home')}>
          Browse produce
        </Button>
      </EmptyState>
    );
  } else if (products.data === undefined && !products.isError) {
    body = (
      <View style={styles.content}>
        <RowSkeleton />
        <RowSkeleton />
        <RowSkeleton />
      </View>
    );
  } else if (products.data === undefined) {
    body = <ErrorState error={products.error} onRetry={() => products.refetch()} retrying={products.isRefetching} />;
  } else {
    body = (
      <>
        <ScrollView contentContainerStyle={styles.content}>
          {holding ? (
            <View style={[styles.holdBanner, { backgroundColor: colors.primaryContainer }]}>
              <MaterialCommunityIcons name="lock-clock" size={24} color={colors.onPrimaryContainer} />
              <View style={styles.flex}>
                <Text variant="titleSmall" style={{ color: colors.onPrimaryContainer }}>
                  These items are held for you
                </Text>
                <Text variant="bodySmall" style={{ color: colors.onPrimaryContainer }}>
                  Changing the cart releases the hold.
                </Text>
              </View>
              <Clock seconds={holdSecondsLeft} size={22} color={colors.onPrimaryContainer} />
            </View>
          ) : null}

          {location ? (
            <Card>
              <View style={styles.deliverRow}>
                <MaterialCommunityIcons name="map-marker" size={22} color={colors.primary} />
                <View style={styles.flex}>
                  <Text variant="titleSmall" numberOfLines={1}>
                    {location.label}
                  </Text>
                  <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
                    {location.hubName} · about {location.etaMinutes} min
                  </Text>
                </View>
                <Button mode="text" compact onPress={() => router.push('/location')}>
                  Change
                </Button>
              </View>
            </Card>
          ) : null}

          <Card>
            {listedLines.map((line, index) => {
              const product = productById.get(line.productId) as Product;
              const short = shortLines.some((shortLine) => shortLine.productId === line.productId);
              const charge = chargeFor(product, line.quantity);
              return (
                <View key={line.productId}>
                  {index > 0 ? <Divider style={styles.lineDivider} /> : null}
                  <View style={styles.line}>
                    <ProductArt
                      name={product.name}
                      category={product.category}
                      imageUrl={product.imageUrl}
                      iconSize={30}
                      style={styles.lineArt}
                    />
                    <View style={styles.flex}>
                      <Text variant="titleSmall" numberOfLines={2}>
                        {product.name}
                      </Text>
                      {product.unitLabel ? (
                        <Text variant="bodySmall" numberOfLines={1} style={{ color: colors.onSurfaceVariant }}>
                          {product.unitLabel}
                        </Text>
                      ) : null}
                      <Text variant="bodySmall" style={[tabularNumbers, { color: colors.onSurfaceVariant }]}>
                        {charge.markedDown > 0 && charge.usual > 0
                          ? `${charge.markedDown} at ${formatRupees(unitPrice(product))}, ${charge.usual} at ${formatRupees(product.price)}`
                          : `${formatRupees(charge.markedDown > 0 ? unitPrice(product) : product.price)} each`}
                      </Text>
                      {short ? (
                        <Text variant="labelMedium" style={{ color: colors.tertiary }}>
                          {product.available > 0 ? `Only ${product.available} left` : 'Sold out just now'}
                        </Text>
                      ) : null}
                    </View>
                    <View style={styles.lineEnd}>
                      <View style={styles.lineStepper}>
                        <QuantityStepper
                          itemName={product.name}
                          quantity={line.quantity}
                          max={holding ? line.quantity : product.available}
                          onChange={(quantity) => setQuantity(line.productId, quantity)}
                        />
                      </View>
                      <Text variant="titleSmall" style={[styles.lineTotal, tabularNumbers]}>
                        {formatRupees(charge.total)}
                      </Text>
                    </View>
                  </View>
                </View>
              );
            })}
          </Card>

          {bill.missingProductIds.length > 0 ? (
            <View style={[styles.notice, { backgroundColor: brand.mangoContainer }]}>
              <MaterialCommunityIcons name="alert-circle-outline" size={20} color={brand.onMangoContainer} />
              <Text variant="bodySmall" style={[styles.flex, { color: brand.onMangoContainer }]}>
                {bill.missingProductIds.length === 1
                  ? 'One item in your cart is no longer listed at your hub.'
                  : `${bill.missingProductIds.length} items in your cart are no longer listed at your hub.`}
              </Text>
            </View>
          ) : null}

          <Card title="Bill">
            <BillSummary
              itemTotal={bill.itemTotal}
              savings={bill.savings}
              deliveryFee={bill.deliveryFee}
              total={bill.total}
              totalLabel="To pay"
            />
          </Card>

          <Text variant="bodySmall" style={[styles.explain, { color: colors.onSurfaceVariant }]}>
            Holding sets your items aside at the hub for 10 minutes while you pay, so nobody else can buy them.
          </Text>
        </ScrollView>

        <View
          style={[
            styles.footer,
            {
              backgroundColor: colors.elevation.level2,
              borderTopColor: colors.outlineVariant,
              paddingBottom: insets.bottom + space.md,
            },
          ]}>
          {createHold.isError ? (
            <Text variant="bodySmall" accessibilityRole="alert" style={{ color: colors.error }}>
              {errorMessage(createHold.error)}
            </Text>
          ) : null}
          {holding ? (
            <Button mode="contained" icon="arrow-right" onPress={() => router.push('/checkout')}>
              Continue to payment
            </Button>
          ) : needsFixing ? (
            <Button mode="contained-tonal" icon="basket-check-outline" onPress={fitCartToStock}>
              Update cart to what is in stock
            </Button>
          ) : (
            <Button
              mode="contained"
              icon="lock-clock"
              onPress={holdItems}
              loading={createHold.isPending}
              disabled={createHold.isPending || bill.lines.length === 0}>
              {`Hold my items · ${formatRupees(bill.total)}`}
            </Button>
          )}
        </View>
      </>
    );
  }

  return (
    <Screen>
      <TopBar title="Your cart" backFallback="/home" />
      {body}
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: space.lg, gap: space.md },
  holdBanner: {
    borderRadius: radius.lg,
    padding: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
  },
  deliverRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  line: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  lineDivider: { marginVertical: space.md },
  lineArt: { width: 56, height: 56 },
  lineEnd: { alignItems: 'flex-end' },
  lineStepper: { width: 128 },
  lineTotal: { minWidth: 64, textAlign: 'right' },
  notice: {
    borderRadius: radius.md,
    padding: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
  },
  explain: { textAlign: 'center', paddingHorizontal: space.lg },
  footer: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    gap: space.sm,
  },
});
