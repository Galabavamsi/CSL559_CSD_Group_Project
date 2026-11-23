import { StyleSheet, View } from 'react-native';
import { Divider, Text } from 'react-native-paper';

import type { OrderLine } from '@/api';
import { formatRupees } from '@/lib/format';
import { fontFamily, space, tabularNumbers, useAppTheme } from '@/theme';

interface BillSummaryProps {
  itemTotal: number;
  savings: number;
  deliveryFee: number;
  total: number;
  /** "To pay" before payment, "Paid" after. */
  totalLabel: string;
}

/** The bill: full price of the items, what rescue deals took off, delivery, and the amount to pay. */
export function BillSummary({ itemTotal, savings, deliveryFee, total, totalLabel }: BillSummaryProps) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.rows}>
      <Row label="Item total" value={formatRupees(itemTotal + savings)} />
      {savings > 0 ? (
        <Row label="Rescue deal savings" value={`− ${formatRupees(savings)}`} color={colors.primary} />
      ) : null}
      <Row
        label="Pooled delivery"
        value={deliveryFee > 0 ? formatRupees(deliveryFee) : 'Free'}
        color={deliveryFee > 0 ? undefined : colors.primary}
      />
      <Divider style={styles.divider} />
      <View style={styles.row}>
        <Text variant="titleMedium">{totalLabel}</Text>
        <Text variant="titleMedium" style={[tabularNumbers, { fontFamily: fontFamily.bold }]}>
          {formatRupees(total)}
        </Text>
      </View>
    </View>
  );
}

function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.row}>
      <Text variant="bodyMedium" style={{ color: colors.onSurfaceVariant }}>
        {label}
      </Text>
      <Text variant="bodyMedium" style={[tabularNumbers, { color: color ?? colors.onSurface }]}>
        {value}
      </Text>
    </View>
  );
}

/** One line of an order summary: "2 × Tomato" with its unit, and what the line costs. */
export function OrderLineRow({ line }: { line: OrderLine }) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.line}>
      <Text variant="bodyMedium" style={[styles.quantity, tabularNumbers, { color: colors.onSurfaceVariant }]}>
        {line.quantity} ×
      </Text>
      <View style={styles.lineText}>
        <Text variant="bodyMedium" numberOfLines={1}>
          {line.name}
        </Text>
        {line.unitLabel ? (
          <Text variant="bodySmall" numberOfLines={1} style={{ color: colors.onSurfaceVariant }}>
            {line.unitLabel}
          </Text>
        ) : null}
      </View>
      <Text variant="bodyMedium" style={tabularNumbers}>
        {formatRupees(line.unitPrice * line.quantity)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  rows: { gap: space.sm },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md },
  divider: { marginVertical: space.xs },
  line: { flexDirection: 'row', alignItems: 'flex-start', gap: space.sm },
  quantity: { width: 32 },
  lineText: { flex: 1 },
});
