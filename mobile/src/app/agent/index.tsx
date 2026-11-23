import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useState, type ReactNode } from 'react';
import { RefreshControl, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, type AgentHub } from '@/api';
import { useAgent, useDeliverOrder, useFailDelivery, useSetAgentDuty } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { DemoNote } from '@/components/DemoNote';
import { KeyboardScroll, KeyboardSpace } from '@/components/KeyboardSpace';
import { RoleHeader } from '@/components/RoleHeader';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { ErrorState } from '@/components/StateViews';
import { Steps, type Step } from '@/components/Steps';
import { BagsAtHub } from '@/features/delivery/BagsAtHub';
import { HubChooser } from '@/features/delivery/HubChooser';
import { StopsOnRoad } from '@/features/delivery/StopsOnRoad';
import { TripSummary } from '@/features/delivery/TripSummary';
import { countOf } from '@/lib/format';
import { fontFamily, radius, space, useAppTheme } from '@/theme';

const HOW_IT_WORKS: Step[] = [
  {
    icon: 'package-variant-closed',
    title: 'Collect the bags',
    text: 'Each bag of your trip waits in a crate slot at the hub. Check every bag before you leave.',
  },
  {
    icon: 'map-marker-path',
    title: 'Follow the stops in order',
    text: 'Stops are listed in the order that keeps the trip short.',
  },
  {
    icon: 'dialpad',
    title: 'Hand over with the code',
    text: "At each door, ask for the customer's 4-digit code and type it in to confirm the handover.",
  },
];

/**
 * The delivery agent's home. One screen that follows where the agent stands: no hub yet, off duty, waiting for a
 * trip, collecting its bags at the hub, on the road, and how the trip went.
 */
export default function AgentHome() {
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const agent = useAgent();
  // Held here and not with the stops: the answer that ends a trip is what the summary is drawn from, and the
  // list of stops is gone by then.
  const deliver = useDeliverOrder();
  const failDelivery = useFailDelivery();
  const [refreshing, setRefreshing] = useState(false);
  const [changingHub, setChangingHub] = useState(false);
  const [closedTripId, setClosedTripId] = useState<number | null>(null);

  const refresh = async () => {
    setRefreshing(true);
    await agent.refetch();
    setRefreshing(false);
  };

  let body: ReactNode;
  if (agent.data === undefined) {
    body = agent.isError ? (
      <Card>
        <ErrorState error={agent.error} onRetry={() => agent.refetch()} retrying={agent.isRefetching} />
      </Card>
    ) : (
      <>
        <Skeleton height={32} width="65%" />
        <Skeleton height={148} rounded={radius.lg} />
        <Skeleton height={56} rounded={radius.xl} />
      </>
    );
  } else {
    const { hub, onDuty, waitingAtHub } = agent.data;
    // A trip that has just ended stays up as a summary until the agent closes it. It is found in the answer to
    // the last stop, and in the agent's state for the moment that still holds it.
    const ended = [deliver.data, failDelivery.data, agent.data.trip].find(
      (trip) => trip != null && trip.status === 'done' && trip.id !== closedTripId,
    );
    const trip = agent.data.trip?.status === 'done' ? null : agent.data.trip;

    if (ended) {
      body = (
        <TripSummary
          trip={ended}
          onDone={() => {
            setClosedTripId(ended.id);
            deliver.reset();
            failDelivery.reset();
          }}
        />
      );
    } else if (trip?.status === 'assigned') {
      body = <BagsAtHub trip={trip} />;
    } else if (trip) {
      body = <StopsOnRoad trip={trip} deliver={deliver} failDelivery={failDelivery} />;
    } else if (hub === null || (changingHub && !onDuty)) {
      body = <HubChooser current={hub} onClose={() => setChangingHub(false)} />;
    } else if (!onDuty) {
      body = <OffDuty hub={hub} waiting={waitingAtHub} onChangeHub={() => setChangingHub(true)} />;
    } else {
      body = <WaitingForTrip hub={hub} waiting={waitingAtHub} />;
    }
  }

  return (
    <Screen padTop>
      <RoleHeader roleLabel="Delivery agent" />
      <KeyboardSpace>
        <KeyboardScroll
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
          {body}
        </KeyboardScroll>
      </KeyboardSpace>
    </Screen>
  );
}

/** "2 bags are waiting at Nehru Nagar Hub." */
function waitingSentence(waiting: number, hubName: string): string {
  if (waiting === 0) return `No bags are waiting at ${hubName} right now.`;
  return `${countOf(waiting, 'bag')} ${waiting === 1 ? 'is' : 'are'} waiting at ${hubName}.`;
}

interface OffDutyProps {
  hub: AgentHub;
  waiting: number;
  onChangeHub: () => void;
}

/** A hub is chosen and the agent is not working: the hub, a way to change it, and the way on duty. */
function OffDuty({ hub, waiting, onChangeHub }: OffDutyProps) {
  const { colors } = useAppTheme();
  const duty = useSetAgentDuty();

  return (
    <>
      <Text variant="headlineSmall" accessibilityRole="header">
        You are off duty
      </Text>
      <Card>
        <View style={styles.row}>
          <View style={[styles.icon, { backgroundColor: colors.primaryContainer }]}>
            <MaterialCommunityIcons name="warehouse" size={22} color={colors.onPrimaryContainer} />
          </View>
          <View style={styles.flex}>
            <Text variant="labelMedium" style={{ color: colors.onSurfaceVariant }}>
              Your hub
            </Text>
            <Text variant="titleMedium">{hub.name}</Text>
          </View>
          <Button mode="text" compact onPress={onChangeHub} disabled={duty.isPending} accessibilityLabel="Change hub">
            Change
          </Button>
        </View>
      </Card>

      <Button
        mode="contained"
        icon="moped"
        onPress={() => duty.mutate(true)}
        loading={duty.isPending}
        disabled={duty.isPending}
        contentStyle={styles.bigButton}
        labelStyle={styles.bigLabel}>
        Go on duty
      </Button>
      {duty.isError ? (
        <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
          {errorMessage(duty.error)}
        </Text>
      ) : null}
      <Text variant="bodyMedium" style={[styles.center, { color: colors.onSurfaceVariant }]}>
        {`${waitingSentence(waiting, hub.name)} On duty, you are given the next trip that leaves this hub.`}
      </Text>

      <Card title="How a delivery run works" style={styles.gap}>
        <Steps steps={HOW_IT_WORKS} />
      </Card>
    </>
  );
}

/** On duty with no trip yet. The screen asks again every few seconds, so the trip shows here on its own. */
function WaitingForTrip({ hub, waiting }: { hub: AgentHub; waiting: number }) {
  const { colors, brand } = useAppTheme();
  const duty = useSetAgentDuty();

  return (
    <>
      <Text variant="headlineSmall" accessibilityRole="header">
        Waiting for a trip
      </Text>
      <View style={[styles.hero, { backgroundColor: brand.mangoContainer }]} accessibilityLiveRegion="polite">
        <View style={[styles.heroIcon, { backgroundColor: colors.elevation.level1 }]}>
          <MaterialCommunityIcons name="timer-sand" size={28} color={colors.onSurface} />
        </View>
        <View style={styles.flex}>
          <Text variant="titleMedium" style={{ color: brand.onMangoContainer }}>
            {waitingSentence(waiting, hub.name)}
          </Text>
          <Text variant="bodyMedium" style={[styles.heroText, { color: brand.onMangoContainer }]}>
            A trip leaves when four orders are packed, or when the oldest has waited ten minutes.
          </Text>
        </View>
      </View>
      <Text variant="bodyMedium" style={[styles.center, { color: colors.onSurfaceVariant }]}>
        Your trip shows here as soon as you are given one.
      </Text>
      <DemoNote>Demo data: a trip with made-up stops appears here in a moment.</DemoNote>

      <Button
        mode="outlined"
        onPress={() => duty.mutate(false)}
        loading={duty.isPending}
        disabled={duty.isPending}
        style={styles.gap}>
        Go off duty
      </Button>
      {duty.isError ? (
        <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
          {errorMessage(duty.error)}
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  content: { padding: space.lg, gap: space.md },
  gap: { marginTop: space.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  icon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  bigButton: { minHeight: 64 },
  bigLabel: { fontFamily: fontFamily.bold, fontSize: 18, lineHeight: 26 },
  hero: { borderRadius: radius.lg, padding: space.lg, flexDirection: 'row', gap: space.md },
  heroIcon: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  heroText: { marginTop: space.xs },
});
