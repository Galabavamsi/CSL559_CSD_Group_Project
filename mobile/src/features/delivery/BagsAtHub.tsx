import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { errorMessage, type Trip, type TripStop } from '@/api';
import { useLoadBag } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { countOf } from '@/lib/format';
import { fontFamily, radius, space, tabularNumbers, useAppTheme } from '@/theme';

/**
 * A trip whose bags are still at the hub. The agent finds each bag by its crate slot and checks it; the API puts
 * the trip on the road when the last one is checked, and this screen gives way to the stops.
 */
export function BagsAtHub({ trip }: { trip: Trip }) {
  const { colors } = useAppTheme();
  const loadBag = useLoadBag();
  const total = trip.stops.length;
  const checked = trip.stops.filter((stop) => stop.status !== 'waiting').length;

  return (
    <View style={styles.block}>
      <View>
        <Text variant="headlineSmall" accessibilityRole="header">
          {`Collect ${countOf(total, 'bag')} at ${trip.hub.name}`}
        </Text>
        <Text variant="bodyMedium" style={[styles.intro, { color: colors.onSurfaceVariant }]}>
          Find each bag by its crate slot and tap Bag checked. The trip starts when every bag is checked.
        </Text>
      </View>

      {trip.stops.map((stop) => (
        <BagRow
          key={stop.orderId}
          stop={stop}
          onCheck={() => loadBag.mutate(stop.orderId)}
          pending={loadBag.isPending && loadBag.variables === stop.orderId}
          disabled={loadBag.isPending}
        />
      ))}

      <Text
        variant="labelLarge"
        accessibilityLiveRegion="polite"
        style={[styles.center, tabularNumbers, { color: colors.onSurfaceVariant }]}>
        {`${checked} of ${countOf(total, 'bag')} checked`}
      </Text>
      {loadBag.isError ? (
        <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
          {errorMessage(loadBag.error)}
        </Text>
      ) : null}
    </View>
  );
}

interface BagRowProps {
  stop: TripStop;
  onCheck: () => void;
  pending: boolean;
  disabled: boolean;
}

/** One bag: the crate slot large, since that is what the agent looks for on the shelf, then whose bag it is. */
function BagRow({ stop, onCheck, pending, disabled }: BagRowProps) {
  const { colors } = useAppTheme();
  const checked = stop.status !== 'waiting';
  const slotInk = checked ? colors.onSurfaceVariant : colors.onPrimaryContainer;

  return (
    <Card>
      <View style={styles.row}>
        <View
          accessible
          accessibilityLabel={stop.crateSlot ? `Crate slot ${stop.crateSlot}` : 'No crate slot recorded'}
          style={[styles.slot, { backgroundColor: checked ? colors.surfaceVariant : colors.primaryContainer }]}>
          {stop.crateSlot ? (
            <Text numberOfLines={1} adjustsFontSizeToFit style={[styles.slotText, { color: slotInk }]}>
              {stop.crateSlot}
            </Text>
          ) : (
            <MaterialCommunityIcons name="package-variant-closed" size={28} color={slotInk} />
          )}
        </View>
        <View style={styles.flex}>
          <Text variant="titleMedium" numberOfLines={1}>
            {stop.orderId}
          </Text>
          <Text variant="bodySmall" style={[tabularNumbers, { color: colors.onSurfaceVariant }]}>
            {`${countOf(stop.units, 'unit')} · ${stop.address.label}`}
          </Text>
          {stop.crateSlot ? null : (
            <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
              No crate slot was recorded. Ask at the packing table.
            </Text>
          )}
        </View>
        {checked ? (
          <MaterialCommunityIcons name="check-circle" size={32} color={colors.primary} accessibilityLabel="Bag checked" />
        ) : null}
      </View>
      {checked ? null : (
        <Button
          mode="contained"
          icon="check"
          onPress={onCheck}
          loading={pending}
          disabled={disabled}
          accessibilityLabel={`Bag checked, order ${stop.orderId}${stop.crateSlot ? `, crate slot ${stop.crateSlot}` : ''}`}
          style={styles.check}>
          Bag checked
        </Button>
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  block: { gap: space.md },
  intro: { marginTop: space.xs },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  slot: {
    minWidth: 84,
    maxWidth: '45%',
    height: 60,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  slotText: { fontFamily: fontFamily.extraBold, fontSize: 26, lineHeight: 32 },
  check: { marginTop: space.md },
});
