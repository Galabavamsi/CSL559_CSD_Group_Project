import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { Order, OrderStatus } from '@/api';
import { ORDER_STEPS, STATUS_INFO, statusTone } from '@/features/orders/status';
import { formatTime } from '@/lib/dates';
import { fontFamily, radius, space, tabularNumbers, useAppTheme, type AppTheme } from '@/theme';

function toneColors(theme: AppTheme, status: OrderStatus): { background: string; foreground: string } {
  const { colors, brand } = theme;
  switch (statusTone(status)) {
    case 'done':
      return { background: colors.primaryContainer, foreground: colors.onPrimaryContainer };
    case 'problem':
      return { background: colors.errorContainer, foreground: colors.onErrorContainer };
    default:
      return { background: brand.mangoContainer, foreground: brand.onMangoContainer };
  }
}

/** A small pill naming an order's state, for lists. */
export function StatusChip({ status }: { status: OrderStatus }) {
  const theme = useAppTheme();
  const { background, foreground } = toneColors(theme, status);
  return (
    <View style={[styles.chip, { backgroundColor: background }]}>
      <MaterialCommunityIcons name={STATUS_INFO[status].icon} size={14} color={foreground} />
      <Text variant="labelMedium" style={{ color: foreground }}>
        {STATUS_INFO[status].label}
      </Text>
    </View>
  );
}

/**
 * The order's path from Placed to Delivered as a vertical line of steps: reached steps are filled and carry
 * their time, the current one explains what is happening, the rest wait. A cancelled or failed order ends its
 * line with that outcome instead of the remaining steps.
 */
export function OrderTimeline({ order }: { order: Order }) {
  const theme = useAppTheme();
  const { colors } = theme;
  const reachedAt = new Map(order.history.map((event) => [event.status, event.at]));
  const offPath = statusTone(order.status) === 'problem';
  const steps: OrderStatus[] = offPath
    ? [...ORDER_STEPS.filter((step) => reachedAt.has(step)), order.status]
    : ORDER_STEPS;

  return (
    <View accessibilityRole="list">
      {steps.map((step, index) => {
        const at = reachedAt.get(step);
        const reached = at !== undefined;
        const current = step === order.status;
        const problem = current && offPath;
        const last = index === steps.length - 1;
        const dot = problem ? colors.error : reached ? colors.primary : colors.surfaceVariant;
        const onDot = problem ? colors.onError : reached ? colors.onPrimary : colors.onSurfaceVariant;
        const info = STATUS_INFO[step];

        return (
          <View
            key={step}
            style={styles.step}
            accessible
            accessibilityRole="text"
            accessibilityLabel={`${info.label}: ${reached ? `done at ${formatTime(at)}` : 'not yet'}`}>
            <View style={styles.rail}>
              <View style={[styles.dot, { backgroundColor: dot }, current && !problem && styles.dotCurrent]}>
                <MaterialCommunityIcons name={reached && !current ? 'check' : info.icon} size={16} color={onDot} />
              </View>
              {last ? null : (
                <View
                  style={[
                    styles.connector,
                    { backgroundColor: reachedAt.has(steps[index + 1]) ? colors.primary : colors.surfaceVariant },
                  ]}
                />
              )}
            </View>
            <View style={[styles.stepText, !last && styles.stepGap]}>
              <View style={styles.stepHeader}>
                <Text
                  variant="titleSmall"
                  style={[
                    styles.flex,
                    {
                      color: problem ? colors.error : reached ? colors.onSurface : colors.onSurfaceVariant,
                      fontFamily: current ? fontFamily.bold : fontFamily.semiBold,
                    },
                  ]}>
                  {info.label}
                </Text>
                {/* The time column keeps its width whether or not a time is in it yet. */}
                <Text variant="bodySmall" style={[styles.time, tabularNumbers, { color: colors.onSurfaceVariant }]}>
                  {reached ? formatTime(at) : ''}
                </Text>
              </View>
              {current ? (
                // Two lines are kept free: the wording differs per step, and the cards below should not jump.
                <Text variant="bodySmall" style={[styles.description, { color: colors.onSurfaceVariant }]}>
                  {info.description}
                </Text>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

interface DeliveryCodeProps {
  code: string | null;
  /** The handover is over: the code has done its job. */
  used: boolean;
}

/** The four digits the customer reads to the delivery agent, large enough to read at arm's length. */
export function DeliveryCode({ code, used }: DeliveryCodeProps) {
  const { colors } = useAppTheme();
  const digits = (code ?? '––––').split('');
  return (
    <View
      accessible
      accessibilityLabel={code ? `Delivery code ${digits.join(' ')}` : 'Delivery code not issued yet'}
      style={[styles.code, used && styles.codeUsed]}>
      {digits.map((digit, index) => (
        <View
          key={index}
          style={[styles.codeCell, { backgroundColor: colors.elevation.level1, borderColor: colors.primary }]}>
          <Text style={[styles.codeDigit, { color: colors.onSurface }]}>{digit}</Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  chip: {
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    height: 24,
  },
  step: { flexDirection: 'row', gap: space.md },
  rail: { alignItems: 'center', width: 28 },
  dot: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  dotCurrent: { transform: [{ scale: 1.15 }] },
  connector: { flex: 1, width: 3, minHeight: 16, borderRadius: 2, marginVertical: 2 },
  stepText: { flex: 1, paddingTop: 4 },
  stepGap: { paddingBottom: space.lg },
  stepHeader: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  time: { minWidth: 64, textAlign: 'right' },
  description: { minHeight: 32 },
  code: { flexDirection: 'row', justifyContent: 'center', gap: space.sm },
  codeUsed: { opacity: 0.45 },
  codeCell: {
    width: 56,
    height: 68,
    borderRadius: radius.md,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  codeDigit: { fontFamily: fontFamily.extraBold, fontSize: 36, lineHeight: 44 },
});
