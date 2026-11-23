import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { Trip } from '@/api';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';

interface TripSummaryProps {
  /** A trip whose every stop is over. */
  trip: Trip;
  onDone: () => void;
}

/** How a trip went, shown once its last stop is over: how many orders were handed over and how many were not. */
export function TripSummary({ trip, onDone }: TripSummaryProps) {
  const { colors } = useAppTheme();
  const delivered = trip.stops.filter((stop) => stop.status === 'delivered').length;
  const failed = trip.stops.filter((stop) => stop.status === 'failed').length;

  return (
    <Card>
      <View style={styles.summary} accessibilityLiveRegion="polite">
        <View style={[styles.iconRing, { backgroundColor: colors.primaryContainer }]}>
          <MaterialCommunityIcons name="flag-checkered" size={40} color={colors.onPrimaryContainer} />
        </View>
        <Text variant="titleLarge" accessibilityRole="header">
          Trip finished
        </Text>
        <View style={styles.counts}>
          <Count
            label="Delivered"
            value={delivered}
            background={colors.primaryContainer}
            ink={colors.onPrimaryContainer}
          />
          <Count
            label="Not delivered"
            value={failed}
            background={failed > 0 ? colors.errorContainer : colors.surfaceVariant}
            ink={failed > 0 ? colors.onErrorContainer : colors.onSurfaceVariant}
          />
        </View>
        {failed > 0 ? (
          <Text variant="bodyMedium" style={[styles.center, { color: colors.onSurfaceVariant }]}>
            {failed === 1
              ? `Take the bag you could not deliver back to ${trip.hub.name}.`
              : `Take the ${failed} bags you could not deliver back to ${trip.hub.name}.`}
          </Text>
        ) : null}
        <Button mode="contained" onPress={onDone} style={styles.done}>
          Done
        </Button>
      </View>
    </Card>
  );
}

function Count({ label, value, background, ink }: { label: string; value: number; background: string; ink: string }) {
  return (
    <View accessible accessibilityLabel={`${label}: ${value}`} style={[styles.count, { backgroundColor: background }]}>
      <Text variant="headlineMedium" style={[tabularNumbers, { color: ink }]}>
        {value}
      </Text>
      <Text variant="labelMedium" style={{ color: ink }}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { textAlign: 'center' },
  summary: { alignItems: 'center', gap: space.md, paddingVertical: space.lg },
  iconRing: { width: 88, height: 88, borderRadius: 44, alignItems: 'center', justifyContent: 'center' },
  counts: { flexDirection: 'row', gap: space.md, alignSelf: 'stretch' },
  count: { flex: 1, borderRadius: radius.md, padding: space.md, alignItems: 'center' },
  done: { alignSelf: 'stretch', marginTop: space.sm },
});
