import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { Dialog, Portal, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, type Farm, type Listing, type ListingStatus, type QualityCheck } from '@/api';
import { useCancelListing, useFarms, useListings } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { RoleHeader } from '@/components/RoleHeader';
import { Screen } from '@/components/Screen';
import { RowSkeleton } from '@/components/Skeleton';
import { EmptyState, ErrorState } from '@/components/StateViews';
import { formatDate, formatSlot } from '@/lib/dates';
import { formatKg, formatRupees } from '@/lib/format';
import { radius, space, tabularNumbers, useAppTheme, type AppTheme } from '@/theme';

/** The farmer's home: the farms they deliver from, and every lot they have listed with what became of it. */
export default function FarmerHome() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const farms = useFarms();
  const listings = useListings();
  const cancelListing = useCancelListing();
  const [refreshing, setRefreshing] = useState(false);
  const [cancelling, setCancelling] = useState<Listing | null>(null);

  const refresh = async () => {
    setRefreshing(true);
    await Promise.all([farms.refetch(), listings.refetch()]);
    setRefreshing(false);
  };

  const hasFarm = (farms.data?.length ?? 0) > 0;

  return (
    <Screen padTop>
      <RoleHeader roleLabel="Farmer" />
      <ScrollView
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
        <View style={styles.sectionHeader}>
          <Text variant="titleLarge" accessibilityRole="header" style={styles.flex}>
            My farms
          </Text>
          <Button mode="contained-tonal" icon="plus" compact onPress={() => router.push('/farmer/add-farm')}>
            Add farm
          </Button>
        </View>
        {farms.data === undefined && !farms.isError ? (
          <RowSkeleton />
        ) : farms.data === undefined ? (
          <Card>
            <ErrorState error={farms.error} onRetry={() => farms.refetch()} retrying={farms.isRefetching} />
          </Card>
        ) : farms.data.length === 0 ? (
          <Card>
            <EmptyState
              icon="barn"
              title="Add your farm first"
              message="Register where your farm is. We use the spot to find the hub you will drop your produce at."
            />
          </Card>
        ) : (
          farms.data.map((farm) => <FarmCard key={farm.id} farm={farm} />)
        )}

        <View style={[styles.sectionHeader, styles.sectionGap]}>
          <Text variant="titleLarge" accessibilityRole="header" style={styles.flex}>
            My listings
          </Text>
          <Button
            mode="contained"
            icon="sprout"
            compact
            disabled={!hasFarm}
            onPress={() => router.push('/farmer/list-produce')}>
            List produce
          </Button>
        </View>
        {listings.data === undefined && !listings.isError ? (
          <>
            <RowSkeleton />
            <RowSkeleton />
          </>
        ) : listings.data === undefined ? (
          <Card>
            <ErrorState error={listings.error} onRetry={() => listings.refetch()} retrying={listings.isRefetching} />
          </Card>
        ) : listings.data.length === 0 ? (
          <Card>
            <EmptyState
              icon="sprout"
              title="Nothing listed yet"
              message={
                hasFarm
                  ? 'List what you are harvesting. You get a hub and a morning drop slot straight away.'
                  : 'Once your farm is registered you can list what you are harvesting.'
              }
            />
          </Card>
        ) : (
          listings.data.map((listing) => (
            <ListingCard
              key={listing.id}
              listing={listing}
              onCancel={() => setCancelling(listing)}
              cancelPending={cancelListing.isPending && cancelListing.variables === listing.id}
            />
          ))
        )}
        {cancelListing.isError ? (
          <Text variant="bodySmall" accessibilityRole="alert" style={[styles.center, { color: colors.error }]}>
            {errorMessage(cancelListing.error)}
          </Text>
        ) : null}
      </ScrollView>

      <Portal>
        <Dialog visible={cancelling !== null} onDismiss={() => setCancelling(null)}>
          <Dialog.Title>Withdraw this listing?</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium">
              {cancelling
                ? `${formatKg(cancelling.qtyKg)} of ${cancelling.itemName} will no longer be expected at ${cancelling.hubName}.`
                : ''}
            </Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={() => setCancelling(null)}>Keep it</Button>
            <Button
              textColor={colors.error}
              onPress={() => {
                if (cancelling) cancelListing.mutate(cancelling.id);
                setCancelling(null);
              }}>
              Withdraw
            </Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </Screen>
  );
}

function FarmCard({ farm }: { farm: Farm }) {
  const { colors } = useAppTheme();
  return (
    <Card>
      <View style={styles.row}>
        <View style={[styles.icon, { backgroundColor: colors.primaryContainer }]}>
          <MaterialCommunityIcons name="barn" size={22} color={colors.onPrimaryContainer} />
        </View>
        <View style={styles.flex}>
          <Text variant="titleMedium" numberOfLines={1}>
            {farm.name}
          </Text>
          <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
            {farm.nearestHub
              ? `Nearest hub: ${farm.nearestHub.name}, ${farm.nearestHub.distanceKm} km away`
              : 'No hub is within reach of this farm yet'}
          </Text>
          {farm.rejectionRate30d !== null ? (
            <Text variant="bodySmall" style={[tabularNumbers, { color: colors.onSurfaceVariant }]}>
              Last 30 days: {formatKg(farm.deliveredKg30d)} delivered, {Math.round(farm.rejectionRate30d * 100)}%
              turned away
            </Text>
          ) : null}
        </View>
      </View>
    </Card>
  );
}

const STATUS_LABEL: Record<ListingStatus, string> = {
  listed: 'Waiting for drop',
  received: 'Checked at hub',
  cancelled: 'Withdrawn',
};

function statusColors(theme: AppTheme, status: ListingStatus): { background: string; foreground: string } {
  const { colors, brand } = theme;
  if (status === 'received') return { background: colors.primaryContainer, foreground: colors.onPrimaryContainer };
  if (status === 'cancelled') return { background: colors.surfaceVariant, foreground: colors.onSurfaceVariant };
  return { background: brand.mangoContainer, foreground: brand.onMangoContainer };
}

interface ListingCardProps {
  listing: Listing;
  onCancel: () => void;
  cancelPending: boolean;
}

/** One lot: what and how much, where and when to drop it, and the hub's verdict once it has been weighed. */
function ListingCard({ listing, onCancel, cancelPending }: ListingCardProps) {
  const theme = useAppTheme();
  const { colors } = theme;
  const chip = statusColors(theme, listing.status);

  return (
    <Card>
      <View style={styles.listingTop}>
        <View style={styles.flex}>
          <Text variant="titleMedium" numberOfLines={1}>
            {listing.itemName}
          </Text>
          <Text variant="bodySmall" style={[tabularNumbers, { color: colors.onSurfaceVariant }]}>
            {formatKg(listing.qtyKg)} at {formatRupees(listing.pricePerKg)} per kg · {listing.farmName}
          </Text>
        </View>
        <View style={[styles.chip, { backgroundColor: chip.background }]}>
          <Text variant="labelMedium" style={{ color: chip.foreground }}>
            {STATUS_LABEL[listing.status]}
          </Text>
        </View>
      </View>

      <View style={styles.facts}>
        <Fact icon="warehouse" label="Drop at" value={listing.hubName} />
        <Fact icon="calendar-clock" label="Drop slot" value={formatSlot(listing.dropFrom, listing.dropUntil)} />
        <Fact icon="sprout" label="Harvest" value={formatDate(listing.harvestDate)} />
      </View>

      {listing.qualityCheck ? <QualityResult check={listing.qualityCheck} /> : null}

      {listing.status === 'listed' ? (
        <Button
          mode="outlined"
          textColor={colors.error}
          onPress={onCancel}
          loading={cancelPending}
          disabled={cancelPending}
          style={styles.cancel}>
          Withdraw listing
        </Button>
      ) : null}
    </Card>
  );
}

function Fact({ icon, label, value }: { icon: 'warehouse' | 'calendar-clock' | 'sprout'; label: string; value: string }) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.fact}>
      <MaterialCommunityIcons name={icon} size={18} color={colors.onSurfaceVariant} />
      <Text variant="bodySmall" style={[styles.factLabel, { color: colors.onSurfaceVariant }]}>
        {label}
      </Text>
      <Text variant="bodyMedium" style={[styles.flex, tabularNumbers]}>
        {value}
      </Text>
    </View>
  );
}

const GRADE_LABEL: Record<QualityCheck['grade'], string> = {
  A: 'Grade A',
  B: 'Grade B',
  C: 'Grade C',
  reject: 'Turned away',
};

/** The hub's quality check: the grade, and how the weight it received split into accepted and rejected. */
function QualityResult({ check }: { check: QualityCheck }) {
  const { colors } = useAppTheme();
  const rejected = check.grade === 'reject';
  return (
    <View
      style={[styles.quality, { backgroundColor: rejected ? colors.errorContainer : colors.primaryContainer }]}
      accessibilityLabel={`Quality check: ${GRADE_LABEL[check.grade]}, ${formatKg(check.acceptedKg)} accepted, ${formatKg(check.rejectedKg)} rejected`}>
      <View style={styles.row}>
        <MaterialCommunityIcons
          name={rejected ? 'close-circle-outline' : 'check-decagram'}
          size={22}
          color={rejected ? colors.onErrorContainer : colors.onPrimaryContainer}
        />
        <Text
          variant="titleSmall"
          style={[styles.flex, { color: rejected ? colors.onErrorContainer : colors.onPrimaryContainer }]}>
          Quality check: {GRADE_LABEL[check.grade]}
        </Text>
      </View>
      <View style={styles.weights}>
        <Weight label="Received" kilograms={check.receivedKg} rejected={rejected} />
        <Weight label="Accepted" kilograms={check.acceptedKg} rejected={rejected} />
        <Weight label="Rejected" kilograms={check.rejectedKg} rejected={rejected} />
      </View>
      {check.remarks ? (
        <Text variant="bodySmall" style={{ color: rejected ? colors.onErrorContainer : colors.onPrimaryContainer }}>
          Hub&apos;s note: {check.remarks}
        </Text>
      ) : null}
    </View>
  );
}

function Weight({ label, kilograms, rejected }: { label: string; kilograms: number; rejected: boolean }) {
  const { colors } = useAppTheme();
  const ink = rejected ? colors.onErrorContainer : colors.onPrimaryContainer;
  return (
    <View style={styles.flex}>
      <Text variant="labelSmall" style={{ color: ink }}>
        {label}
      </Text>
      <Text variant="titleMedium" style={[tabularNumbers, { color: ink }]}>
        {formatKg(kilograms)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  content: { padding: space.lg, gap: space.md },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  sectionGap: { marginTop: space.lg },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  icon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  listingTop: { flexDirection: 'row', alignItems: 'flex-start', gap: space.md },
  chip: { borderRadius: radius.pill, paddingHorizontal: 10, height: 24, justifyContent: 'center' },
  facts: { marginTop: space.md, gap: space.sm },
  fact: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  factLabel: { width: 64 },
  quality: { marginTop: space.md, borderRadius: radius.md, padding: space.md, gap: space.sm },
  weights: { flexDirection: 'row', gap: space.md },
  cancel: { marginTop: space.md },
});
