import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useState, type ReactNode } from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { Dialog, Portal, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError, type Order } from '@/api';
import { isFinalStatus, useCancelOrder, useOrder } from '@/api/queries';
import { BillSummary, OrderLineRow } from '@/components/BillSummary';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { DeliveryCode, OrderTimeline } from '@/components/OrderStatus';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { TopBar } from '@/components/TopBar';
import { STATUS_INFO, statusTone } from '@/features/orders/status';
import { formatDayTime, formatTime } from '@/lib/dates';
import { radius, space, useAppTheme } from '@/theme';

export default function OrderTracking() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const order = useOrder(id);
  const cancelOrder = useCancelOrder();
  const [refreshing, setRefreshing] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    await order.refetch();
    setRefreshing(false);
  };

  let body: ReactNode;
  if (order.data) {
    body = (
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + space.xl }]}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
            colors={[colors.primary]}
            tintColor={colors.primary}
            progressBackgroundColor={colors.elevation.level2}
          />
        }>
        <StatusHero order={order.data} />

        {statusTone(order.data.status) !== 'problem' ? (
          <Card title="Delivery code">
            <DeliveryCode code={order.data.deliveryCode} used={order.data.status === 'delivered'} />
            <Text variant="bodySmall" style={[styles.codeHint, { color: colors.onSurfaceVariant }]}>
              {order.data.status === 'delivered'
                ? 'This code confirmed the handover.'
                : order.data.deliveryCode
                  ? 'Read this code to the delivery agent at your door. They type it in to confirm the handover, so share it only then.'
                  : 'Your code appears here once the hub has planned your delivery.'}
            </Text>
          </Card>
        ) : null}

        <Card title="Progress">
          <OrderTimeline order={order.data} />
        </Card>

        {!isFinalStatus(order.data.status) ? (
          <>
            <PooledNote order={order.data} />
            <AgentPanel order={order.data} />
          </>
        ) : null}

        <Card title="Deliver to">
          <Text variant="bodyLarge">{order.data.address.line}</Text>
          <Text variant="bodyMedium" style={{ color: colors.onSurfaceVariant }}>
            {[order.data.address.landmark, order.data.address.label].filter(Boolean).join(' · ')}
          </Text>
        </Card>

        <Card title="Items">
          <View style={styles.lines}>
            {order.data.lines.map((line) => (
              <OrderLineRow key={`${line.productId}-${line.unitPrice}`} line={line} />
            ))}
          </View>
          <View style={styles.bill}>
            <BillSummary
              itemTotal={order.data.itemTotal}
              savings={order.data.savings}
              deliveryFee={order.data.deliveryFee}
              total={order.data.total}
              totalLabel={
                order.data.status === 'placed' ? 'To pay' : order.data.status === 'cancelled' ? 'Order total' : 'Paid'
              }
            />
          </View>
        </Card>

        {order.data.canCancel ? (
          <View>
            <Button
              mode="outlined"
              textColor={colors.error}
              onPress={() => setConfirmingCancel(true)}
              loading={cancelOrder.isPending}
              disabled={cancelOrder.isPending}>
              Cancel order
            </Button>
            <Text variant="bodySmall" style={[styles.cancelHint, { color: colors.onSurfaceVariant }]}>
              You can cancel until the hub has packed your items.
            </Text>
          </View>
        ) : null}
        {cancelOrder.isError ? (
          <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
            {errorMessage(cancelOrder.error)}
          </Text>
        ) : null}
      </ScrollView>
    );
  } else if (order.isPending) {
    body = (
      <View style={styles.content}>
        <Skeleton height={112} rounded={radius.lg} />
        <Skeleton height={148} rounded={radius.lg} />
        <Skeleton height={280} rounded={radius.lg} />
      </View>
    );
  } else if (isApiError(order.error, 'not_found')) {
    body = (
      <EmptyState
        icon="receipt-text-outline"
        title="Order not found"
        message="This order is not in your account on this device.">
        <Button mode="contained" onPress={() => router.replace('/orders')}>
          See my orders
        </Button>
      </EmptyState>
    );
  } else {
    body = <ErrorState error={order.error} onRetry={() => order.refetch()} retrying={order.isRefetching} />;
  }

  return (
    <Screen>
      <TopBar title={`Order ${id}`} backFallback="/orders" />
      {body}
      <Portal>
        <Dialog visible={confirmingCancel} onDismiss={() => setConfirmingCancel(false)}>
          <Dialog.Title>Cancel this order?</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium">The items go back on sale for your neighbours.</Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setConfirmingCancel(false)}>Keep order</Button>
            <Button
              textColor={colors.error}
              onPress={() => {
                setConfirmingCancel(false);
                cancelOrder.mutate(id);
              }}>
              Cancel order
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </Screen>
  );
}

/** The headline of the screen: where the order is now, in words, with when it should arrive. */
function StatusHero({ order }: { order: Order }) {
  const { colors, brand } = useAppTheme();
  const info = STATUS_INFO[order.status];
  const tone = statusTone(order.status);
  const background =
    tone === 'problem' ? colors.errorContainer : tone === 'done' ? colors.primaryContainer : brand.mangoContainer;
  const ink =
    tone === 'problem' ? colors.onErrorContainer : tone === 'done' ? colors.onPrimaryContainer : brand.onMangoContainer;

  const arrival =
    order.etaMinutes !== null ? new Date(new Date(order.placedAt).getTime() + order.etaMinutes * 60_000) : null;
  const reachedAt = order.history[order.history.length - 1]?.at;
  const footnote =
    tone === 'active' && arrival
      ? `Expected by ${formatTime(arrival.toISOString())} · from ${order.hubName}`
      : reachedAt
        ? `${formatDayTime(reachedAt)} · from ${order.hubName}`
        : `From ${order.hubName}`;

  return (
    <View style={[styles.hero, { backgroundColor: background }]} accessibilityLiveRegion="polite">
      <View style={[styles.heroIcon, { backgroundColor: colors.elevation.level1 }]}>
        <MaterialCommunityIcons name={info.icon} size={28} color={colors.onSurface} />
      </View>
      <View style={styles.flex}>
        <Text variant="titleLarge" style={{ color: ink }}>
          {info.label}
        </Text>
        {/* Two lines are kept free so the cards below do not jump when the wording changes with the status. */}
        <Text variant="bodyMedium" style={[styles.heroText, { color: ink }]}>
          {info.description}
        </Text>
        <Text variant="labelMedium" style={{ color: ink }}>
          {footnote}
        </Text>
      </View>
    </View>
  );
}

/** Why the order may wait a little before leaving the hub: it shares its ride. */
function PooledNote({ order }: { order: Order }) {
  const { colors } = useAppTheme();
  let text =
    "Once packed, your bag is grouped with your neighbours' orders into one delivery run. One trip for many homes keeps delivery free.";
  if (order.pooledWith === 0) {
    // Nobody nearby ordered in time: the bag went on its own rather than keep the customer waiting.
    text = 'No neighbour ordered in the same few minutes, so your bag has a trip to itself this time.';
  } else if (order.pooledWith !== null) {
    text = `Your bag rides with ${order.pooledWith} other ${order.pooledWith === 1 ? 'order' : 'orders'} from your neighbourhood. One trip instead of ${order.pooledWith + 1} keeps delivery free.`;
  }
  return (
    <View style={[styles.note, { backgroundColor: colors.secondaryContainer }]}>
      <MaterialCommunityIcons name="account-group-outline" size={24} color={colors.onSecondaryContainer} />
      <View style={styles.flex}>
        <Text variant="titleSmall" style={{ color: colors.onSecondaryContainer }}>
          Pooled delivery
        </Text>
        <Text variant="bodySmall" style={{ color: colors.onSecondaryContainer }}>
          {text}
        </Text>
      </View>
    </View>
  );
}

/** Stands where the live map of the delivery agent will go once a maps SDK is added. */
function AgentPanel({ order }: { order: Order }) {
  const { colors } = useAppTheme();
  const onTheWay = order.status === 'out_for_delivery';
  return (
    <View style={[styles.agent, { borderColor: colors.outline, backgroundColor: colors.elevation.level1 }]}>
      <MaterialCommunityIcons name="map-marker-path" size={32} color={onTheWay ? colors.primary : colors.outline} />
      <View style={styles.flex}>
        <Text variant="titleSmall">
          {onTheWay && order.agentName ? `${order.agentName} is on the way` : 'Delivery agent'}
        </Text>
        <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
          {onTheWay
            ? "The agent's live position on a map will show in this panel."
            : "The agent's position shows here once your order is out for delivery."}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  content: { padding: space.lg, gap: space.md },
  hero: { borderRadius: radius.lg, padding: space.lg, flexDirection: 'row', gap: space.md },
  heroIcon: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  heroText: { minHeight: 40, marginVertical: 2 },
  codeHint: { textAlign: 'center', marginTop: space.md },
  note: { borderRadius: radius.lg, padding: space.lg, flexDirection: 'row', gap: space.md },
  agent: {
    borderRadius: radius.lg,
    borderWidth: 1,
    borderStyle: 'dashed',
    padding: space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
  },
  lines: { gap: space.md },
  bill: { marginTop: space.lg },
  cancelHint: { textAlign: 'center', marginTop: space.sm },
});
