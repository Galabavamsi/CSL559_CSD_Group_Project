import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState, type ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { HelperText, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError, type Listing } from '@/api';
import { useCreateListing, useFarms, useProduceItems } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { Skeleton } from '@/components/Skeleton';
import { ErrorState } from '@/components/StateViews';
import { TextField } from '@/components/TextField';
import { TopBar } from '@/components/TopBar';
import { formatDate, formatSlot, isoDateAfter } from '@/lib/dates';
import { formatKg, formatRupees } from '@/lib/format';
import { newIdempotencyKey } from '@/lib/ids';
import { radius, space, TOUCH_TARGET, useAppTheme } from '@/theme';

/** Harvest dates offered, as days from today: a lot picked up to three days ago, or due within the week. */
const HARVEST_DAYS = [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7];

function harvestLabel(daysFromToday: number): string {
  if (daysFromToday === 0) return 'Today';
  if (daysFromToday === -1) return 'Yesterday';
  if (daysFromToday === 1) return 'Tomorrow';
  return formatDate(isoDateAfter(daysFromToday));
}

/** A positive number typed with a dot or a comma; null for anything else. */
function parseAmount(text: string): number | null {
  const value = Number(text.trim().replace(',', '.'));
  return text.trim() !== '' && Number.isFinite(value) && value > 0 ? value : null;
}

/** List a lot: which farm, what, how much, at what price, harvested when. The answer is a hub and a drop slot. */
export default function ListProduce() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const farms = useFarms();
  const items = useProduceItems();
  const createListing = useCreateListing();

  const [chosenFarmId, setChosenFarmId] = useState<number | null>(null);
  const [itemId, setItemId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [harvestDay, setHarvestDay] = useState(0);
  const [showErrors, setShowErrors] = useState(false);
  // One key per version of the form: sending the same form twice (a retry, a double tap) lists the lot once,
  // and a form that was changed counts as a new request.
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);
  const editing =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      setIdempotencyKey(newIdempotencyKey());
    };

  // A farmer with one farm does not have to choose it.
  const farmId = chosenFarmId ?? (farms.data?.length === 1 ? farms.data[0].id : null);
  const item = items.data?.find((candidate) => candidate.id === itemId) ?? null;
  const qtyKg = parseAmount(quantity);
  const pricePerKg = parseAmount(price);

  const submit = () => {
    if (farmId === null || itemId === null || qtyKg === null || pricePerKg === null) {
      setShowErrors(true);
      return;
    }
    createListing.mutate({
      listing: { farmId, itemId, qtyKg, pricePerKg, harvestDate: isoDateAfter(harvestDay) },
      idempotencyKey,
    });
  };

  let body: ReactNode;
  if (createListing.data) {
    body = <Listed listing={createListing.data} onDone={() => router.back()} />;
  } else if ((farms.data === undefined || items.data === undefined) && !farms.isError && !items.isError) {
    body = (
      <View style={styles.content}>
        <Skeleton height={120} rounded={radius.lg} />
        <Skeleton height={220} rounded={radius.lg} />
        <Skeleton height={160} rounded={radius.lg} />
      </View>
    );
  } else if (farms.data === undefined || items.data === undefined) {
    body = (
      <ErrorState
        error={farms.error ?? items.error}
        onRetry={() => {
          farms.refetch();
          items.refetch();
        }}
        retrying={farms.isRefetching || items.isRefetching}
      />
    );
  } else {
    const passedOver = isApiError(createListing.error, 'no_hub_with_room') ? createListing.error.details.hubs : null;
    body = (
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Card title="From which farm?">
            <View style={styles.choices} accessibilityRole="radiogroup">
              {farms.data.map((farm) => (
                <Choice
                  key={farm.id}
                  label={farm.name}
                  selected={farm.id === farmId}
                  onPress={() => editing(setChosenFarmId)(farm.id)}
                />
              ))}
            </View>
            <FieldError visible={showErrors && farmId === null}>Choose the farm this lot comes from</FieldError>
          </Card>

          <Card title="What are you listing?">
            <View style={styles.choices} accessibilityRole="radiogroup">
              {items.data.map((option) => (
                <Choice
                  key={option.id}
                  label={option.name}
                  selected={option.id === itemId}
                  onPress={() => editing(setItemId)(option.id)}
                />
              ))}
            </View>
            <FieldError visible={showErrors && itemId === null}>Choose what you are listing</FieldError>
            {item ? (
              <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
                {`Keeps ${item.shelfLifeDays} days from harvest.`}
                {item.units.length > 0
                  ? ` Customers buy it as: ${item.units.map((unit) => unit.unitLabel ?? unit.name).join(', ')}.`
                  : ''}
              </Text>
            ) : null}
          </Card>

          <Card title="How much, and at what price?">
            <TextField
              label="Quantity"
              value={quantity}
              onChangeText={editing(setQuantity)}
              error={showErrors && qtyKg === null}
              keyboardType="decimal-pad"
              inputMode="decimal"
              maxLength={8}
              right={<TextField.Affix text="kg" />}
            />
            <FieldError visible={showErrors && qtyKg === null}>Enter the weight in kilograms, for example 50</FieldError>
            <TextField
              label="Price per kg"
              value={price}
              onChangeText={editing(setPrice)}
              error={showErrors && pricePerKg === null}
              keyboardType="decimal-pad"
              inputMode="decimal"
              maxLength={8}
              left={<TextField.Affix text="₹" />}
            />
            <FieldError visible={showErrors && pricePerKg === null}>Enter your price for one kilogram</FieldError>
            {qtyKg !== null && pricePerKg !== null ? (
              <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
                {`${formatKg(qtyKg)} at ${formatRupees(pricePerKg)} per kg comes to ${formatRupees(qtyKg * pricePerKg)} if the hub accepts all of it.`}
              </Text>
            ) : null}
          </Card>

          <Card title="Harvest date">
            <View style={styles.choices} accessibilityRole="radiogroup">
              {HARVEST_DAYS.map((day) => (
                <Choice
                  key={day}
                  label={harvestLabel(day)}
                  selected={day === harvestDay}
                  onPress={() => editing(setHarvestDay)(day)}
                />
              ))}
            </View>
          </Card>

          {createListing.isError ? (
            <View style={[styles.refused, { backgroundColor: colors.errorContainer }]} accessibilityRole="alert">
              <MaterialCommunityIcons name="alert-circle-outline" size={22} color={colors.onErrorContainer} />
              <View style={styles.flex}>
                <Text variant="bodyMedium" style={{ color: colors.onErrorContainer }}>
                  {errorMessage(createListing.error)}
                </Text>
                {Array.isArray(passedOver)
                  ? passedOver.map((hub: { store?: unknown; reason?: unknown }, index) => (
                      <Text key={index} variant="bodySmall" style={{ color: colors.onErrorContainer }}>
                        {`${String(hub.store)}: ${String(hub.reason)}`}
                      </Text>
                    ))
                  : null}
              </View>
            </View>
          ) : null}
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
          <Button
            mode="contained"
            icon="sprout"
            onPress={submit}
            loading={createListing.isPending}
            disabled={createListing.isPending}>
            List produce
          </Button>
        </View>
      </KeyboardAvoidingView>
    );
  }

  return (
    <Screen>
      <TopBar title="List produce" backFallback="/farmer" />
      {body}
    </Screen>
  );
}

/** A pill that can be chosen, at least 48 dp tall. */
function Choice({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { colors } = useAppTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="radio"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={label}
      style={styles.choiceTouch}>
      <View
        style={[
          styles.choice,
          selected
            ? { backgroundColor: colors.primary, borderColor: colors.primary }
            : { backgroundColor: colors.elevation.level1, borderColor: colors.outline },
        ]}>
        <Text variant="labelLarge" style={{ color: selected ? colors.onPrimary : colors.onSurface }}>
          {label}
        </Text>
      </View>
    </Pressable>
  );
}

/** A line under a field that is always there, so the form does not move when a message appears in it. */
function FieldError({ visible, children }: { visible: boolean; children: string }) {
  return (
    <HelperText type="error" visible={visible} style={styles.helper}>
      {visible ? children : ' '}
    </HelperText>
  );
}

/** The answer to a listing: which hub, and when to bring the lot. */
function Listed({ listing, onDone }: { listing: Listing; onDone: () => void }) {
  const { colors } = useAppTheme();
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <View style={[styles.listed, { backgroundColor: colors.primaryContainer }]}>
        <MaterialCommunityIcons name="check-decagram" size={40} color={colors.onPrimaryContainer} />
        <Text variant="headlineSmall" style={{ color: colors.onPrimaryContainer }}>
          Your lot is listed
        </Text>
        <Text variant="bodyMedium" style={[styles.center, { color: colors.onPrimaryContainer }]}>
          {`${formatKg(listing.qtyKg)} of ${listing.itemName} from ${listing.farmName}`}
        </Text>
      </View>
      <Card title="Where and when to drop it">
        <View style={styles.answer}>
          <MaterialCommunityIcons name="warehouse" size={24} color={colors.primary} />
          <View style={styles.flex}>
            <Text variant="labelMedium" style={{ color: colors.onSurfaceVariant }}>
              Hub
            </Text>
            <Text variant="titleMedium">{listing.hubName}</Text>
          </View>
        </View>
        <View style={styles.answer}>
          <MaterialCommunityIcons name="calendar-clock" size={24} color={colors.primary} />
          <View style={styles.flex}>
            <Text variant="labelMedium" style={{ color: colors.onSurfaceVariant }}>
              Drop slot
            </Text>
            <Text variant="titleMedium">{formatSlot(listing.dropFrom, listing.dropUntil)}</Text>
          </View>
        </View>
        <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
          The hub weighs and grades the lot when you bring it. The result shows under My listings.
        </Text>
      </Card>
      <Button mode="contained" onPress={onDone}>
        Back to my listings
      </Button>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { textAlign: 'center' },
  content: { padding: space.lg, gap: space.md },
  choices: { flexDirection: 'row', flexWrap: 'wrap', columnGap: space.sm },
  choiceTouch: { height: TOUCH_TARGET, justifyContent: 'center' },
  choice: {
    height: 36,
    borderRadius: radius.pill,
    borderWidth: 1,
    paddingHorizontal: 14,
    justifyContent: 'center',
  },
  helper: { minHeight: 24 },
  refused: { borderRadius: radius.lg, padding: space.lg, flexDirection: 'row', gap: space.md },
  footer: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
  },
  listed: { borderRadius: radius.lg, padding: space.xl, alignItems: 'center', gap: space.sm },
  answer: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginBottom: space.md },
});
