import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { Dialog, Portal, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError, type Serviceability, type ServiceRequestResult } from '@/api';
import { useCities, useRequestService, useServiceability } from '@/api/queries';
import { Button } from '@/components/Button';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { ErrorState } from '@/components/StateViews';
import { TopBar } from '@/components/TopBar';
import { emptyCart } from '@/features/cart/useCartActions';
import { LocationPicker, type PickedPoint } from '@/features/location/LocationPicker';
import { cartUnitCount, useCart } from '@/state/cart';
import { useDeliveryLocation } from '@/state/deliveryLocation';
import { useSession } from '@/state/session';
import { radius, space, useAppTheme } from '@/theme';

export default function DeliveryLocationScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();

  const saved = useDeliveryLocation((state) => state.location);
  const setLocation = useDeliveryLocation((state) => state.setLocation);
  const profileCity = useSession((state) => state.user?.city ?? null);
  const cartHubId = useCart((state) => state.hubId);
  const cartCount = useCart((state) => cartUnitCount(state.quantities));

  const [point, setPoint] = useState<PickedPoint | null>(
    saved ? { label: saved.label, lat: saved.lat, lng: saved.lng } : null,
  );
  const [confirmingHubChange, setConfirmingHubChange] = useState(false);

  const cities = useCities();
  const check = useServiceability(point);
  const result = point ? check.data : undefined;

  // Where nobody delivers yet, the customer can ask. The answer is remembered for the point it was asked at.
  const requestService = useRequestService();
  const [asked, setAsked] = useState<{ at: string; answer: ServiceRequestResult } | null>(null);
  const pointKey = point ? `${point.lat},${point.lng}` : null;
  const askedHere = asked !== null && asked.at === pointKey ? asked.answer : null;
  const unserved = result !== undefined && !result.serviceable;

  const ask = () => {
    if (!point || pointKey === null) return;
    requestService.mutate(
      { point: { lat: point.lat, lng: point.lng }, label: point.label },
      {
        onSuccess: (answer) => setAsked({ at: pointKey, answer }),
        // A hub opened here since the check: look again, and the screen offers delivery instead.
        onError: (error) => {
          if (isApiError(error, 'already_served')) void check.refetch();
        },
      },
    );
  };

  const save = (served: Extract<Serviceability, { serviceable: true }>) => {
    if (!point) return;
    if (cartHubId !== null && cartHubId !== served.hubId) emptyCart();
    setLocation({
      label: point.label,
      lat: point.lat,
      lng: point.lng,
      hubId: served.hubId,
      hubName: served.hubName,
      etaMinutes: served.etaMinutes,
      h3Cell: served.h3Cell,
    });
    if (router.canGoBack()) router.back();
    else router.replace('/home');
  };

  const confirm = () => {
    if (!result?.serviceable) return;
    // Stock belongs to a hub. A cart filled at another hub cannot come along.
    if (cartCount > 0 && cartHubId !== null && cartHubId !== result.hubId) setConfirmingHubChange(true);
    else save(result);
  };

  return (
    <Screen>
      <TopBar title="Delivery location" showBack={saved !== null} backFallback="/home" />
      {cities.data === undefined && !cities.isError ? (
        <View style={styles.content}>
          <Skeleton height={48} rounded={radius.xl} />
          <Skeleton height={48} rounded={radius.xl} style={styles.gap} />
          <Skeleton height={260} rounded={radius.lg} style={styles.gap} />
        </View>
      ) : cities.data === undefined ? (
        <ErrorState error={cities.error} onRetry={() => cities.refetch()} retrying={cities.isRefetching} />
      ) : (
        <>
          <ScrollView contentContainerStyle={styles.content}>
            <Text variant="bodyLarge" style={[styles.intro, { color: colors.onSurfaceVariant }]}>
              Tell us where to deliver. We show what the hub serving your address has in stock.
            </Text>
            <LocationPicker
              cities={cities.data}
              initialCitySlug={profileCity}
              value={point}
              onChange={(next) => {
                setPoint(next);
                requestService.reset();
              }}
            />
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
            <ServiceabilityResult
              point={point}
              result={result}
              loading={point !== null && check.isPending}
              failed={point !== null && check.isError}
              onRetry={() => check.refetch()}
              asked={askedHere}
            />
            {unserved ? (
              <>
                {requestService.isError && askedHere === null ? (
                  <Text variant="bodySmall" accessibilityRole="alert" style={{ color: colors.error }}>
                    {errorMessage(requestService.error)}
                  </Text>
                ) : null}
                <Button
                  mode="contained"
                  icon={askedHere ? 'check' : 'map-marker-plus-outline'}
                  onPress={ask}
                  loading={requestService.isPending}
                  disabled={requestService.isPending || askedHere !== null}>
                  {askedHere ? 'Request sent' : 'Request delivery here'}
                </Button>
              </>
            ) : (
              <Button mode="contained" onPress={confirm} disabled={!result?.serviceable}>
                Deliver here
              </Button>
            )}
          </View>
        </>
      )}

      <Portal>
        <Dialog visible={confirmingHubChange} onDismiss={() => setConfirmingHubChange(false)}>
          <Dialog.Title>Empty your cart?</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium">
              This address is served by a different hub with its own stock. Your cart from the current hub will be
              emptied.
            </Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setConfirmingHubChange(false)}>Keep my cart</Button>
            <Button
              onPress={() => {
                setConfirmingHubChange(false);
                if (result?.serviceable) save(result);
              }}>
              Change address
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </Screen>
  );
}

interface ServiceabilityResultProps {
  point: PickedPoint | null;
  result: Serviceability | undefined;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  /** The answer to this customer's request for delivery at this point, once they have asked. */
  asked: ServiceRequestResult | null;
}

/** One fixed-height line of verdict above the confirm button: served by which hub and how soon, or not served. */
function ServiceabilityResult({ point, result, loading, failed, onRetry, asked }: ServiceabilityResultProps) {
  const { colors } = useAppTheme();

  let icon:
    | 'map-marker-outline'
    | 'map-marker-check-outline'
    | 'map-marker-off-outline'
    | 'map-marker-plus-outline'
    | 'alert-circle-outline' = 'map-marker-outline';
  let iconColor = colors.onSurfaceVariant;
  let title = 'No address chosen yet';
  let detail = 'Use your current location or pick an area above.';

  if (failed) {
    icon = 'alert-circle-outline';
    iconColor = colors.error;
    title = 'Could not check this address';
    detail = 'Tap to try again.';
  } else if (result?.serviceable) {
    icon = 'map-marker-check-outline';
    iconColor = colors.primary;
    title = `We deliver to ${point?.label ?? 'this address'}`;
    detail = `${result.hubName} · about ${result.etaMinutes} min${result.hubStatus === 'busy' ? ' (busy right now)' : ''}`;
  } else if (result) {
    icon = 'map-marker-off-outline';
    iconColor = colors.tertiary;
    title = 'Not in our delivery area yet';
    detail =
      result.nearestHubName && result.nearestDistanceKm !== null
        ? `The nearest hub, ${result.nearestHubName}, is ${result.nearestDistanceKm.toFixed(1)} km away.`
        : 'No hub is close to this address.';
    if (asked) {
      icon = 'map-marker-plus-outline';
      iconColor = colors.primary;
      title = 'We have noted your request';
      detail =
        asked.othersNearby === 0
          ? 'You are the first to ask from here. Hubs open where the most people ask.'
          : `${asked.othersNearby} ${asked.othersNearby === 1 ? 'neighbour has' : 'neighbours have'} asked too. Hubs open where the most people ask.`;
    } else {
      detail += ' Ask for delivery here and we count it when choosing the next hub.';
    }
  }

  return (
    <Pressable
      onPress={onRetry}
      disabled={!failed}
      accessibilityRole={failed ? 'button' : undefined}
      accessibilityLiveRegion="polite"
      style={styles.result}>
      {loading ? (
        <>
          <Skeleton width={36} height={36} rounded={18} />
          <View style={styles.resultText}>
            <Skeleton height={16} width="70%" />
            <Skeleton height={12} width="50%" style={styles.gapSmall} />
          </View>
        </>
      ) : (
        <>
          <MaterialCommunityIcons name={icon} size={32} color={iconColor} />
          <View style={styles.resultText}>
            <Text variant="titleSmall" numberOfLines={1}>
              {title}
            </Text>
            <Text variant="bodySmall" numberOfLines={2} style={{ color: colors.onSurfaceVariant }}>
              {detail}
            </Text>
          </View>
        </>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: space.lg, paddingTop: space.sm, paddingBottom: space.xl },
  intro: { marginBottom: space.lg },
  gap: { marginTop: space.md },
  gapSmall: { marginTop: space.sm },
  footer: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    gap: space.md,
  },
  result: { flexDirection: 'row', alignItems: 'center', gap: space.md, minHeight: 52 },
  resultText: { flex: 1 },
});
