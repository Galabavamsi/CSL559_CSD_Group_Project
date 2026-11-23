import { ScrollView, StyleSheet } from 'react-native';
import { Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Card } from '@/components/Card';
import { RoleHeader } from '@/components/RoleHeader';
import { Screen } from '@/components/Screen';
import { EmptyState } from '@/components/StateViews';
import { Steps, type Step } from '@/components/Steps';
import { space } from '@/theme';

const HOW_IT_WORKS: Step[] = [
  {
    icon: 'package-variant-closed',
    title: 'Collect the batch',
    text: 'The hub pools orders for one neighbourhood into a batch and hands you the sealed bags.',
  },
  {
    icon: 'map-marker-path',
    title: 'Follow the stops in order',
    text: 'Stops are listed in the order that keeps the run short.',
  },
  {
    icon: 'dialpad',
    title: 'Confirm with the code',
    text: "At each door, ask for the customer's 4-digit code and type it in to confirm the handover.",
  },
];

/** The delivery agent's home. The batch itself arrives with the delivery work; this is where it will show. */
export default function AgentHome() {
  const insets = useSafeAreaInsets();
  return (
    <Screen padTop>
      <RoleHeader roleLabel="Delivery agent" />
      <ScrollView contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + space.xl }]}>
        <Text variant="headlineSmall" accessibilityRole="header">
          Today&apos;s batch
        </Text>
        <Card>
          <EmptyState
            icon="moped-outline"
            title="No batch assigned yet"
            message="When your hub pools the next set of orders for your area, the batch and its stops appear here."
          />
        </Card>
        <Card title="How a delivery run works">
          <Steps steps={HOW_IT_WORKS} />
        </Card>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { padding: space.lg, gap: space.md },
});
