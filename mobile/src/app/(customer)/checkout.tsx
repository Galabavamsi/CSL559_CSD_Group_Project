import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Redirect, useRouter } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { ActivityIndicator, HelperText, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api, errorMessage, isApiError } from '@/api';
import { useCreateHold, useHold, usePlaceOrder, useProducts, useReleaseHold } from '@/api/queries';
import { BillSummary, OrderLineRow } from '@/components/BillSummary';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { HoldCountdown } from '@/components/HoldCountdown';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { TextField } from '@/components/TextField';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { TopBar } from '@/components/TopBar';
import { computeBill } from '@/lib/bill';
import { secondsUntil } from '@/lib/dates';
import { useNow } from '@/lib/hooks';
import { newOrderId } from '@/lib/ids';
import { formatRupees } from '@/lib/format';
import { cartLines, useCart } from '@/state/cart';
import { useDeliveryLocation } from '@/state/deliveryLocation';
import { radius, space, useAppTheme } from '@/theme';

/** Reservation states that mean the stock is no longer set aside for this cart. */
const GIVEN_BACK = ['released', 'expired', 'cancelled'];

export default function Checkout() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const now = useNow();

  const location = useDeliveryLocation((state) => state.location);
  const savedLine = useDeliveryLocation((state) => state.addressLine);
  const savedLandmark = useDeliveryLocation((state) => state.landmark);
  const setAddress = useDeliveryLocation((state) => state.setAddress);
  const hold = useCart((state) => state.hold);
  const quantities = useCart((state) => state.quantities);

  const products = useProducts(hold?.hubId ?? null);
  const holdCheck = useHold(hold?.id ?? null);
  const placeOrder = usePlaceOrder();
  const releaseHold = useReleaseHold();
  const createHold = useCreateHold();

  const [addressLine, setAddressLine] = useState(savedLine);
  const [landmark, setLandmark] = useState(savedLandmark);
  const [addressMissing, setAddressMissing] = useState(false);

  if (!hold || !location) {
    // A paid order empties the cart, and with it the hold this screen is about, a moment before the order
    // screen opens. Anything else without a hold (a link opened directly) belongs on the cart.
    if (!placeOrder.isPending && !placeOrder.isSuccess) return <Redirect href="/cart" />;
    return (
      <Screen>
        <TopBar title="Checkout" showBack={false} />
        <View style={styles.placing} accessibilityRole="progressbar" accessibilityLabel="Placing your order">
          <ActivityIndicator size="large" />
          <Text variant="titleMedium">Placing your order</Text>
        </View>
      </Screen>
    );
  }

  const lines = cartLines(quantities);
  const bill = computeBill(lines, products.data ?? []);
  const expired =
    secondsUntil(hold.expiresAt, now) <= 0 ||
    (holdCheck.data !== undefined && GIVEN_BACK.includes(holdCheck.data.status)) ||
    isApiError(holdCheck.error, 'not_found') ||
    isApiError(placeOrder.error, 'hold_expired') ||
    isApiError(placeOrder.error, 'not_held');

  const pay = () => {
    const line = addressLine.trim();
    if (line === '') {
      setAddressMissing(true);
      return;
    }
    setAddress(line, landmark.trim());
    placeOrder.mutate(
      {
        holdId: hold.id,
        hubName: location.hubName,
        lines: bill.lines,
        itemTotal: bill.itemTotal,
        savings: bill.savings,
        deliveryFee: bill.deliveryFee,
        total: bill.total,
        address: {
          label: location.label,
          line,
          landmark: landmark.trim() || null,
          lat: location.lat,
          lng: location.lng,
        },
        etaMinutes: location.etaMinutes,
      },
      {
        onSuccess: (order) => {
          // Leave the shop on the stack and the cart and checkout off it: "back" from the order goes to the shop.
          router.dismissTo('/home');
          router.push({ pathname: '/order/[id]', params: { id: order.id } });
        },
      },
    );
  };

  const holdAgain = () => {
    placeOrder.reset();
    createHold.mutate({ orderId: newOrderId(), hubId: hold.hubId, lines, h3Cell: location.h3Cell });
  };

  const cancel = () => {
    releaseHold.mutate(hold.id);
    router.dismissTo('/cart');
  };

  if (expired) {
    return (
      <Screen>
        <TopBar title="Checkout" backFallback="/cart" />
        <EmptyState
          icon="timer-sand"
          title="Your hold ran out"
          message="The time to pay is over, so the items went back on sale. Your cart is still here: hold the items again to carry on.">
          <Button
            mode="contained"
            icon="lock-clock"
            onPress={holdAgain}
            loading={createHold.isPending}
            disabled={createHold.isPending}>
            Hold my items again
          </Button>
          <Button mode="text" onPress={() => router.replace('/cart')}>
            Back to cart
          </Button>
          {createHold.isError ? (
            <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
              {errorMessage(createHold.error)} Go back to your cart to adjust it.
            </Text>
          ) : null}
        </EmptyState>
      </Screen>
    );
  }

  const busy = placeOrder.isPending || releaseHold.isPending;

  return (
    <Screen>
      <TopBar title="Checkout" backFallback="/cart" />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <HoldCountdown hold={hold} hubName={location.hubName} now={now} />

          <Card title="Deliver to">
            <View style={styles.area}>
              <MaterialCommunityIcons name="map-marker" size={20} color={colors.primary} />
              <Text variant="bodyLarge" style={styles.flex} numberOfLines={1}>
                {location.label}
              </Text>
            </View>
            <TextField
              label="House or flat, street"
              value={addressLine}
              onChangeText={(text) => {
                setAddressLine(text);
                setAddressMissing(false);
              }}
              error={addressMissing}
              autoComplete="street-address"
              textContentType="streetAddressLine1"
              maxLength={120}
              style={styles.input}
            />
            <HelperText type="error" visible={addressMissing} style={styles.helper}>
              {addressMissing ? 'The delivery agent needs your house or flat number' : ' '}
            </HelperText>
            <TextField
              label="Landmark (optional)"
              value={landmark}
              onChangeText={setLandmark}
              maxLength={80}
            />
          </Card>

          <Card title="Your order">
            {products.data === undefined && products.isError ? (
              <ErrorState error={products.error} onRetry={() => products.refetch()} retrying={products.isRefetching} />
            ) : products.data === undefined ? (
              <Skeleton height={72} />
            ) : (
              <View style={styles.lines}>
                {bill.lines.map((line) => (
                  <OrderLineRow key={line.productId} line={line} />
                ))}
              </View>
            )}
            <View style={styles.bill}>
              <BillSummary
                itemTotal={bill.itemTotal}
                savings={bill.savings}
                deliveryFee={bill.deliveryFee}
                total={bill.total}
                totalLabel="To pay"
              />
            </View>
          </Card>

          <View style={[styles.payment, { backgroundColor: colors.secondaryContainer }]}>
            <MaterialCommunityIcons name="shield-check-outline" size={22} color={colors.onSecondaryContainer} />
            <Text variant="bodySmall" style={[styles.flex, { color: colors.onSecondaryContainer }]}>
              {api.mode === 'mock'
                ? 'Demo payment: tapping Pay places the order and no money is taken.'
                : 'Test payment: this version confirms the order with the hub and takes no money.'}
            </Text>
          </View>
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
          {placeOrder.isError ? (
            <Text variant="bodySmall" accessibilityRole="alert" style={{ color: colors.error }}>
              {errorMessage(placeOrder.error)}
            </Text>
          ) : null}
          <Button
            mode="contained"
            icon="check-circle-outline"
            onPress={pay}
            loading={placeOrder.isPending}
            disabled={busy || bill.lines.length === 0}>
            {`Pay ${formatRupees(bill.total)}`}
          </Button>
          <Button mode="text" onPress={cancel} loading={releaseHold.isPending} disabled={busy}>
            Cancel and release my items
          </Button>
        </View>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  placing: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.lg },
  content: { padding: space.lg, gap: space.md },
  area: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  input: { marginTop: space.md },
  helper: { minHeight: 24 },
  lines: { gap: space.md },
  bill: { marginTop: space.lg },
  payment: {
    borderRadius: radius.md,
    padding: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
  },
  footer: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    gap: space.xs,
  },
});
