import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useState } from 'react';
import { Keyboard, StyleSheet, View } from 'react-native';
import { Dialog, Portal, RadioButton, Text } from 'react-native-paper';

import { errorMessage, isApiError, type DeliveryFailReason, type Trip, type TripStop } from '@/api';
import { MOCK_DOOR_CODE } from '@/api/mock/data';
import type { useDeliverOrder, useFailDelivery } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { DemoNote } from '@/components/DemoNote';
import { OtpInput } from '@/components/OtpInput';
import type { IconName } from '@/features/catalogue/categories';
import { countOf, formatKm } from '@/lib/format';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';

import { callNumber, openInMaps } from './links';
import { FAIL_REASONS, failReasonLabel } from './reasons';

const CODE_LENGTH = 4;

type DeliverOrder = ReturnType<typeof useDeliverOrder>;
type FailDelivery = ReturnType<typeof useFailDelivery>;

interface StopsOnRoadProps {
  trip: Trip;
  /** Held by the screen, not here: the answer to the last stop of a trip outlives this list. */
  deliver: DeliverOrder;
  failDelivery: FailDelivery;
}

/**
 * A trip on the road: its stops in the order they are made. The first bag still with the agent is the door they
 * are going to, and only that stop is open; the others show as one line each.
 */
export function StopsOnRoad({ trip, deliver, failDelivery }: StopsOnRoadProps) {
  const { colors } = useAppTheme();
  const [reporting, setReporting] = useState<TripStop | null>(null);
  const current = trip.stops.find((stop) => stop.status === 'loaded') ?? null;

  return (
    <View style={styles.block}>
      <View>
        <Text variant="headlineSmall" accessibilityRole="header" accessibilityLiveRegion="polite">
          {current ? `Stop ${current.seq} of ${trip.stops.length}` : 'On the road'}
        </Text>
        <Text variant="bodyMedium" style={[styles.intro, tabularNumbers, { color: colors.onSurfaceVariant }]}>
          {`${countOf(trip.stops.length, 'stop')} · ${formatKm(trip.km)} planned · from ${trip.hub.name}`}
        </Text>
      </View>

      <View accessibilityRole="list" style={styles.block}>
        {trip.stops.map((stop) =>
          stop === current ? (
            <CurrentStop
              key={stop.orderId}
              stop={stop}
              deliver={deliver}
              failDelivery={failDelivery}
              onReport={() => setReporting(stop)}
            />
          ) : (
            <StopRow key={stop.orderId} stop={stop} />
          ),
        )}
      </View>

      <FailDialog
        stop={reporting}
        onDismiss={() => setReporting(null)}
        onConfirm={(reason) => {
          if (reporting) failDelivery.mutate({ orderId: reporting.orderId, reason });
          setReporting(null);
        }}
      />
    </View>
  );
}

interface CurrentStopProps {
  stop: TripStop;
  deliver: DeliverOrder;
  failDelivery: FailDelivery;
  onReport: () => void;
}

/** The door the agent is going to: where it is, who to ask for, and the hand-over against the customer's code. */
function CurrentStop({ stop, deliver, failDelivery, onReport }: CurrentStopProps) {
  const { colors } = useAppTheme();
  const [code, setCode] = useState('');
  const [linkProblem, setLinkProblem] = useState<string | null>(null);

  // Both actions belong to the whole trip, so each still holds what happened at the door before this one.
  const deliverError = deliver.variables?.orderId === stop.orderId ? deliver.error : null;
  const reportError = failDelivery.variables?.orderId === stop.orderId ? failDelivery.error : null;
  const busy = deliver.isPending || failDelivery.isPending;

  // After a wrong code the API says how many tries are left; the stop itself says so once it has been read again.
  const wrongCode = isApiError(deliverError, 'wrong_code');
  const triesSaid = wrongCode ? deliverError.details.tries_left : undefined;
  const triesLeft = typeof triesSaid === 'number' ? Math.min(triesSaid, stop.triesLeft) : stop.triesLeft;
  const locked = triesLeft <= 0 || isApiError(deliverError, 'code_locked');

  const changeCode = (next: string) => {
    setCode(next);
    // The last digit puts the keyboard away, so the button under the field can be seen and tapped.
    if (next.length === CODE_LENGTH) Keyboard.dismiss();
  };

  const handOver = () => {
    if (code.length !== CODE_LENGTH || busy) return;
    deliver.mutate(
      { orderId: stop.orderId, code },
      {
        // A wrong code is typed afresh. After any other failure the same digits can be sent again.
        onError: (error) => {
          if (isApiError(error, 'wrong_code')) setCode('');
        },
      },
    );
  };

  const call = async () => {
    const { phone } = stop.customer;
    if (!phone) return;
    setLinkProblem(null);
    if (!(await callNumber(phone))) setLinkProblem(`This device cannot start a call. The number is ${phone}.`);
  };

  const showOnMap = async () => {
    setLinkProblem(null);
    if (!(await openInMaps(stop.address))) setLinkProblem('No maps app could be opened on this device.');
  };

  return (
    <Card style={[styles.current, { borderColor: colors.primary }]}>
      <View style={styles.head}>
        <View style={[styles.mark, { backgroundColor: colors.primary }]}>
          <Text variant="labelLarge" style={{ color: colors.onPrimary }}>
            {stop.seq}
          </Text>
        </View>
        <View style={styles.flex}>
          <Text variant="titleLarge">{stop.address.label}</Text>
          <Text variant="bodyLarge">{stop.address.line}</Text>
          {stop.address.landmark ? (
            <Text variant="bodyMedium" style={{ color: colors.onSurfaceVariant }}>
              {`Landmark: ${stop.address.landmark}`}
            </Text>
          ) : null}
        </View>
      </View>

      <View style={styles.facts}>
        {stop.customer.name ? <Fact icon="account-outline" text={stop.customer.name} /> : null}
        <Fact
          icon="package-variant-closed"
          text={`Order ${stop.orderId} · ${countOf(stop.units, 'unit')}${stop.crateSlot ? ` · slot ${stop.crateSlot}` : ''}`}
        />
        {stop.customer.phone ? null : <Fact icon="phone-off-outline" text="The customer gave no phone number" />}
      </View>

      <View style={styles.links}>
        {stop.customer.phone ? (
          <Button
            mode="contained-tonal"
            icon="phone"
            onPress={call}
            accessibilityLabel={`Call ${stop.customer.name ?? 'the customer'}`}
            style={styles.flex}>
            Call
          </Button>
        ) : null}
        <Button
          mode="contained-tonal"
          icon="map-marker-radius-outline"
          onPress={showOnMap}
          accessibilityLabel={`Open ${stop.address.label} in maps`}
          style={styles.flex}>
          Open in maps
        </Button>
      </View>
      {linkProblem ? (
        <Text variant="bodySmall" accessibilityRole="alert" style={[styles.message, { color: colors.error }]}>
          {linkProblem}
        </Text>
      ) : null}

      <View style={[styles.handOver, { borderTopColor: colors.outlineVariant }]}>
        {locked ? (
          <View accessibilityRole="alert" style={[styles.locked, { backgroundColor: colors.errorContainer }]}>
            <MaterialCommunityIcons name="lock-alert-outline" size={24} color={colors.onErrorContainer} />
            <View style={styles.flex}>
              <Text variant="titleSmall" style={{ color: colors.onErrorContainer }}>
                Too many wrong codes
              </Text>
              <Text variant="bodySmall" style={{ color: colors.onErrorContainer }}>
                The code can no longer be tried for this order. Report the stop as not delivered. The hub will call
                the customer.
              </Text>
            </View>
          </View>
        ) : (
          <>
            <Text variant="titleSmall">Ask the customer for their 4-digit code</Text>
            <OtpInput
              value={code}
              onChange={changeCode}
              length={CODE_LENGTH}
              hasError={wrongCode && code === ''}
              disabled={busy}
              autoFocus={false}
              fromMessages={false}
              accessibilityLabel="4-digit delivery code"
            />
            {deliverError ? (
              <Text variant="bodySmall" accessibilityRole="alert" style={{ color: colors.error }}>
                {wrongCode
                  ? `${errorMessage(deliverError)} ${countOf(triesLeft, 'try', 'tries')} left.`
                  : errorMessage(deliverError)}
              </Text>
            ) : null}
            <DemoNote>{`Demo data: the code at every door is ${MOCK_DOOR_CODE}.`}</DemoNote>
            <Button
              mode="contained"
              icon="check-circle-outline"
              onPress={handOver}
              loading={deliver.isPending}
              disabled={code.length !== CODE_LENGTH || busy}>
              Hand over
            </Button>
          </>
        )}
        <Button
          mode={locked ? 'contained' : 'text'}
          textColor={locked ? undefined : colors.error}
          onPress={onReport}
          loading={failDelivery.isPending}
          disabled={busy}>
          Could not deliver
        </Button>
        {reportError ? (
          <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
            {errorMessage(reportError)}
          </Text>
        ) : null}
      </View>
    </Card>
  );
}

function Fact({ icon, text }: { icon: IconName; text: string }) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.fact}>
      <MaterialCommunityIcons name={icon} size={18} color={colors.onSurfaceVariant} />
      <Text variant="bodyMedium" style={[styles.flex, tabularNumbers]}>
        {text}
      </Text>
    </View>
  );
}

/** A stop that is not the current one, as one line: where, and how it went or that it is still to come. */
function StopRow({ stop }: { stop: TripStop }) {
  const { colors } = useAppTheme();
  const delivered = stop.status === 'delivered';
  const failed = stop.status === 'failed';
  const reason = failReasonLabel(stop.failedReason);
  const outcome = delivered ? 'Delivered' : failed ? (reason ? `Not delivered. ${reason}.` : 'Not delivered') : null;

  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLabel={`Stop ${stop.seq}, ${stop.address.label}. ${outcome ?? 'Still to come'}`}
      style={[styles.row, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
      <View
        style={[
          styles.mark,
          { backgroundColor: delivered ? colors.primary : failed ? colors.error : colors.surfaceVariant },
        ]}>
        {delivered ? (
          <MaterialCommunityIcons name="check" size={18} color={colors.onPrimary} />
        ) : failed ? (
          <MaterialCommunityIcons name="close" size={18} color={colors.onError} />
        ) : (
          <Text variant="labelLarge" style={{ color: colors.onSurfaceVariant }}>
            {stop.seq}
          </Text>
        )}
      </View>
      <View style={styles.flex}>
        <Text variant="titleSmall" numberOfLines={1}>
          {stop.address.label}
        </Text>
        <Text variant="bodySmall" numberOfLines={1} style={{ color: failed ? colors.error : colors.onSurfaceVariant }}>
          {outcome ?? stop.address.line}
        </Text>
      </View>
    </View>
  );
}

interface FailDialogProps {
  /** The stop being reported; null keeps the dialog closed. */
  stop: TripStop | null;
  onDismiss: () => void;
  onConfirm: (reason: DeliveryFailReason) => void;
}

/** Asks why an order could not be handed over, and reports it only once a reason is chosen and confirmed. */
function FailDialog({ stop, onDismiss, onConfirm }: FailDialogProps) {
  const { colors } = useAppTheme();
  const [reason, setReason] = useState<DeliveryFailReason | null>(null);

  const close = (confirmed: DeliveryFailReason | null) => {
    setReason(null); // the next stop starts with nothing chosen
    if (confirmed) onConfirm(confirmed);
    else onDismiss();
  };

  return (
    <Portal>
      <Dialog visible={stop !== null} onDismiss={() => close(null)}>
        <Dialog.Title>Why could you not deliver?</Dialog.Title>
        <Dialog.Content>
          <RadioButton.Group value={reason ?? ''} onValueChange={(value) => setReason(value as DeliveryFailReason)}>
            {FAIL_REASONS.map((option) => (
              <RadioButton.Item
                key={option.value}
                value={option.value}
                label={option.label}
                mode="android"
                position="leading"
                labelStyle={styles.reasonLabel}
                style={styles.reason}
              />
            ))}
          </RadioButton.Group>
          <Text variant="bodySmall" style={[styles.message, { color: colors.onSurfaceVariant }]}>
            The order is marked as not delivered and the bag goes back to the hub with you.
          </Text>
        </Dialog.Content>
        <Dialog.Actions>
          <Button onPress={() => close(null)}>Go back</Button>
          <Button textColor={colors.error} disabled={reason === null} onPress={() => close(reason)}>
            Report not delivered
          </Button>
        </Dialog.Actions>
      </Dialog>
    </Portal>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  block: { gap: space.md },
  intro: { marginTop: space.xs },
  current: { borderWidth: 2 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md },
  mark: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  facts: { marginTop: space.md, gap: space.sm },
  fact: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  links: { marginTop: space.lg, flexDirection: 'row', gap: space.sm },
  message: { marginTop: space.sm },
  handOver: {
    marginTop: space.lg,
    paddingTop: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: space.md,
  },
  locked: { borderRadius: radius.md, padding: space.md, flexDirection: 'row', gap: space.md },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    padding: space.md,
  },
  reason: { paddingHorizontal: 0 },
  reasonLabel: { textAlign: 'left' },
});
