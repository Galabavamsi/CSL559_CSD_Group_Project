import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { Order } from '@/api';
import { useOrders } from '@/api/queries';
import { Button } from '@/components/Button';
import { StatusChip } from '@/components/OrderStatus';
import { Screen } from '@/components/Screen';
import { RowSkeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatDayTime } from '@/lib/dates';
import { formatRupees } from '@/lib/format';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';

export default function Orders() {
  const router = useRouter();
  const { colors } = useAppTheme();
  const orders = useOrders();
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async () => {
    setRefreshing(true);
    await orders.refetch();
    setRefreshing(false);
  };

  return (
    <Screen padTop>
      <Text variant="headlineSmall" accessibilityRole="header" style={styles.heading}>
        Your orders
      </Text>
      {orders.data === undefined && !orders.isError ? (
        <View style={styles.list}>
          <RowSkeleton />
          <RowSkeleton />
          <RowSkeleton />
        </View>
      ) : orders.data === undefined ? (
        <ErrorState error={orders.error} onRetry={() => orders.refetch()} retrying={orders.isRefetching} />
      ) : (
        <FlatList
          data={orders.data}
          keyExtractor={(order) => order.id}
          contentContainerStyle={styles.list}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={refresh}
              colors={[colors.primary]}
              tintColor={colors.primary}
              progressBackgroundColor={colors.elevation.level2}
            />
          }
          ListEmptyComponent={
            <EmptyState
              icon="receipt-text-outline"
              title="No orders yet"
              message="When you place an order you can follow it here, from the hub to your door.">
              <Button mode="contained" onPress={() => router.navigate('/home')}>
                Start shopping
              </Button>
            </EmptyState>
          }
          renderItem={({ item }) => (
            <OrderRow order={item} onPress={() => router.push({ pathname: '/order/[id]', params: { id: item.id } })} />
          )}
        />
      )}
    </Screen>
  );
}

function OrderRow({ order, onPress }: { order: Order; onPress: () => void }) {
  const { colors } = useAppTheme();
  const units = order.lines.reduce((sum, line) => sum + line.quantity, 0);
  const names = [...new Set(order.lines.map((line) => line.name))].join(', ');

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Order ${order.id}, ${order.status.replace(/_/g, ' ')}, ${formatRupees(order.total)}`}
      accessibilityHint="Opens the order"
      android_ripple={{ color: colors.surfaceVariant }}
      style={({ pressed }) => [
        styles.row,
        { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant },
        pressed && styles.pressed,
      ]}>
      <View style={styles.rowTop}>
        <StatusChip status={order.status} />
        <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
          {formatDayTime(order.placedAt)}
        </Text>
      </View>
      <Text variant="titleSmall" numberOfLines={1} style={styles.names}>
        {names}
      </Text>
      <View style={styles.rowBottom}>
        <Text variant="bodySmall" style={[styles.flex, tabularNumbers, { color: colors.onSurfaceVariant }]}>
          {units} {units === 1 ? 'item' : 'items'} · {order.id}
        </Text>
        <Text variant="titleSmall" style={tabularNumbers}>
          {formatRupees(order.total)}
        </Text>
        <MaterialCommunityIcons name="chevron-right" size={20} color={colors.onSurfaceVariant} />
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  heading: { paddingHorizontal: space.lg, paddingTop: space.lg, paddingBottom: space.sm },
  list: { flexGrow: 1, padding: space.lg, gap: space.md },
  row: {
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: space.lg,
    overflow: 'hidden',
  },
  pressed: { opacity: 0.8 },
  rowTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: space.sm },
  names: { marginTop: space.md },
  rowBottom: { flexDirection: 'row', alignItems: 'center', gap: space.sm, marginTop: space.xs },
});
