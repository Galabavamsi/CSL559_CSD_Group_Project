import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { errorMessage, type AgentHub } from '@/api';
import { useChooseAgentHub, useCities, useHubs } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Segmented } from '@/components/Segmented';
import { RowSkeleton, Skeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { useSession } from '@/state/session';
import { radius, space, useAppTheme } from '@/theme';

interface HubChooserProps {
  /** The hub the agent works from now, when they are changing it; null the first time. */
  current: AgentHub | null;
  /** A hub was chosen, or the agent decided to keep the one they have. */
  onClose: () => void;
}

/** Where an agent says which hub they collect bags from: a city, then one of its hubs. Only while off duty. */
export function HubChooser({ current, onClose }: HubChooserProps) {
  const { colors } = useAppTheme();
  const profileCity = useSession((state) => state.user?.city ?? null);
  const cities = useCities();
  const chooseHub = useChooseAgentHub();
  const [pickedCity, setPickedCity] = useState<string | null>(null);
  const [hubId, setHubId] = useState<number | null>(current?.id ?? null);

  // Until the agent picks a city, the one on their profile shows; failing that, the first.
  const citySlug =
    pickedCity ?? cities.data?.find((city) => city.slug === profileCity)?.slug ?? cities.data?.[0]?.slug ?? null;
  const hubs = useHubs(citySlug);
  // A closed hub gives out no trips, and the API refuses it.
  const open = hubs.data?.filter((hub) => hub.status !== 'closed');
  const picked = open?.find((hub) => hub.id === hubId) ?? null;

  return (
    <View style={styles.block}>
      <Text variant="headlineSmall" accessibilityRole="header">
        {current ? 'Change your hub' : 'Choose your hub'}
      </Text>
      <Text variant="bodyLarge" style={{ color: colors.onSurfaceVariant }}>
        Pick the hub you collect bags from. On duty, you are given trips from that hub.
      </Text>

      {cities.data === undefined && !cities.isError ? (
        <>
          <Skeleton height={48} rounded={radius.xl} />
          <RowSkeleton />
          <RowSkeleton />
        </>
      ) : cities.data === undefined ? (
        <Card>
          <ErrorState error={cities.error} onRetry={() => cities.refetch()} retrying={cities.isRefetching} />
        </Card>
      ) : (
        <>
          {cities.data.length > 1 ? (
            <Segmented
              options={cities.data.map((city) => ({ value: city.slug, label: city.name }))}
              value={citySlug}
              onChange={setPickedCity}
              accessibilityLabel="City"
            />
          ) : null}

          {open === undefined && citySlug !== null && !hubs.isError ? (
            <>
              <RowSkeleton />
              <RowSkeleton />
            </>
          ) : open === undefined && hubs.isError ? (
            <Card>
              <ErrorState error={hubs.error} onRetry={() => hubs.refetch()} retrying={hubs.isRefetching} />
            </Card>
          ) : open === undefined || open.length === 0 ? (
            <Card>
              <EmptyState
                icon="warehouse"
                title="No hub is open here"
                message="No hub in this city is giving out trips right now."
              />
            </Card>
          ) : (
            <View
              accessibilityRole="radiogroup"
              accessibilityLabel="Hub"
              style={[styles.list, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
              {open.map((hub, index) => {
                const selected = hub.id === hubId;
                const busy = hub.status === 'busy';
                return (
                  <Pressable
                    key={hub.id}
                    onPress={() => setHubId(hub.id)}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: selected }}
                    accessibilityLabel={busy ? `${hub.name}, busy right now` : hub.name}
                    android_ripple={{ color: colors.surfaceVariant }}
                    style={[
                      styles.row,
                      index > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.outlineVariant },
                      selected && { backgroundColor: colors.primaryContainer },
                    ]}>
                    <MaterialCommunityIcons
                      name="warehouse"
                      size={22}
                      color={selected ? colors.onPrimaryContainer : colors.onSurfaceVariant}
                    />
                    <View style={styles.rowText}>
                      <Text
                        variant="bodyLarge"
                        style={{ color: selected ? colors.onPrimaryContainer : colors.onSurface }}>
                        {hub.name}
                      </Text>
                      {busy ? (
                        <Text
                          variant="bodySmall"
                          style={{ color: selected ? colors.onPrimaryContainer : colors.onSurfaceVariant }}>
                          Busy right now
                        </Text>
                      ) : null}
                    </View>
                    {selected ? (
                      <MaterialCommunityIcons name="check" size={20} color={colors.onPrimaryContainer} />
                    ) : null}
                  </Pressable>
                );
              })}
            </View>
          )}

          {chooseHub.isError ? (
            <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
              {errorMessage(chooseHub.error)}
            </Text>
          ) : null}
          <Button
            mode="contained"
            icon="warehouse"
            onPress={() => {
              if (picked) chooseHub.mutate(picked.id, { onSuccess: onClose });
            }}
            loading={chooseHub.isPending}
            disabled={picked === null || picked.id === current?.id || chooseHub.isPending}>
            Work from this hub
          </Button>
          {current ? (
            <Button mode="text" onPress={onClose} disabled={chooseHub.isPending}>
              {`Keep ${current.name}`}
            </Button>
          ) : null}
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  block: { gap: space.md },
  center: { textAlign: 'center' },
  list: { borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, overflow: 'hidden' },
  row: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
  rowText: { flex: 1 },
});
