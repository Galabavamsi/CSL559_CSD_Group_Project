import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import * as Location from 'expo-location';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { HelperText, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError } from '@/api';
import { useCreateFarm } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { TextField } from '@/components/TextField';
import { TopBar } from '@/components/TopBar';
import { radius, space, tabularNumbers, useAppTheme } from '@/theme';
import { KeyboardScroll, KeyboardSpace } from '@/components/KeyboardSpace';

/** What the phone said about where it is. */
interface Fix {
  lat: number;
  lng: number;
  /** Metres; null when the phone did not say how sure it is. */
  accuracyM: number | null;
}

const BETTER_FIX_TIPS = [
  'Stand in the open, away from buildings and trees.',
  'Turn on precise location for this app if your phone asks.',
  'Wait ten to twenty seconds, then read the location again.',
];

/** Register a farm: its name, and the spot the farmer is standing on. */
export default function AddFarm() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors, brand } = useAppTheme();
  const createFarm = useCreateFarm();

  const [name, setName] = useState('');
  const [nameMissing, setNameMissing] = useState(false);
  const [fix, setFix] = useState<Fix | null>(null);
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState<string | null>(null);

  const readLocation = async () => {
    setLocating(true);
    setGpsError(null);
    createFarm.reset();
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) {
        setGpsError('Location access is off. Allow it for this app in your phone settings, then try again.');
        return;
      }
      const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setFix({
        lat: position.coords.latitude,
        lng: position.coords.longitude,
        accuracyM: position.coords.accuracy,
      });
    } catch {
      setGpsError('Could not read your location. Check that location is switched on, then try again.');
    } finally {
      setLocating(false);
    }
  };

  const save = () => {
    const farmName = name.trim();
    if (farmName === '') {
      setNameMissing(true);
      return;
    }
    if (!fix) return;
    createFarm.mutate({ name: farmName, ...fix }, { onSuccess: () => router.back() });
  };

  // The hub wants a location it can trust. The API says how rough ours was and what it needs.
  const tooRough = isApiError(createFarm.error, 'location_too_rough') ? createFarm.error.details : null;
  const otherError = createFarm.isError && tooRough === null;

  return (
    <Screen>
      <TopBar title="Add farm" backFallback="/farmer" />
      <KeyboardSpace>
        <KeyboardScroll contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <Card title="Farm name">
            <TextField
              label="Name"
              value={name}
              onChangeText={(text) => {
                setName(text);
                setNameMissing(false);
              }}
              error={nameMissing}
              maxLength={80}
            />
            <HelperText type="error" visible={nameMissing} style={styles.helper}>
              {nameMissing ? 'Give the farm a name you will recognise, for example "Home field"' : ' '}
            </HelperText>
          </Card>

          <Card title="Where is it?">
            <Text variant="bodyMedium" style={{ color: colors.onSurfaceVariant }}>
              Stand at the farm and read your location. We use the spot to choose the hub you drop your produce at.
            </Text>

            {fix ? (
              <View style={[styles.fix, { backgroundColor: colors.surfaceVariant }]}>
                <MaterialCommunityIcons name="map-marker-check-outline" size={24} color={colors.primary} />
                <View style={styles.flex}>
                  <Text variant="titleSmall" style={tabularNumbers}>
                    {fix.lat.toFixed(5)}, {fix.lng.toFixed(5)}
                  </Text>
                  <Text variant="bodySmall" style={[tabularNumbers, { color: colors.onSurfaceVariant }]}>
                    {fix.accuracyM !== null
                      ? `The phone is sure of this to about ${Math.round(fix.accuracyM)} m`
                      : 'The phone did not say how sure it is'}
                  </Text>
                </View>
              </View>
            ) : null}

            <Button
              mode={fix ? 'outlined' : 'contained-tonal'}
              icon="crosshairs-gps"
              onPress={readLocation}
              loading={locating}
              disabled={locating}
              style={styles.read}>
              {fix ? 'Read my location again' : 'Read my location'}
            </Button>
            <HelperText type="error" visible={gpsError !== null} style={styles.helper}>
              {gpsError ?? ' '}
            </HelperText>
          </Card>

          {tooRough ? (
            <View style={[styles.rough, { backgroundColor: brand.mangoContainer }]} accessibilityRole="alert">
              <View style={styles.roughTitle}>
                <MaterialCommunityIcons name="crosshairs-question" size={24} color={brand.onMangoContainer} />
                <Text variant="titleSmall" style={[styles.flex, { color: brand.onMangoContainer }]}>
                  The location is not precise enough yet
                </Text>
              </View>
              <Text variant="bodyMedium" style={{ color: brand.onMangoContainer }}>
                {typeof tooRough.accuracy_m === 'number' && typeof tooRough.needed_m === 'number'
                  ? `Your phone knows this spot only to about ${Math.round(tooRough.accuracy_m)} m. The hub needs ${Math.round(tooRough.needed_m)} m or better, so the farm was not saved.`
                  : errorMessage(createFarm.error)}
              </Text>
              {BETTER_FIX_TIPS.map((tip) => (
                <View key={tip} style={styles.tip}>
                  <Text variant="bodySmall" style={{ color: brand.onMangoContainer }}>
                    •
                  </Text>
                  <Text variant="bodySmall" style={[styles.flex, { color: brand.onMangoContainer }]}>
                    {tip}
                  </Text>
                </View>
              ))}
            </View>
          ) : null}
        </KeyboardScroll>

        <View
          style={[
            styles.footer,
            {
              backgroundColor: colors.elevation.level2,
              borderTopColor: colors.outlineVariant,
              paddingBottom: insets.bottom + space.md,
            },
          ]}>
          {otherError ? (
            <Text variant="bodySmall" accessibilityRole="alert" style={{ color: colors.error }}>
              {errorMessage(createFarm.error)}
            </Text>
          ) : null}
          <Button
            mode="contained"
            onPress={save}
            loading={createFarm.isPending}
            disabled={fix === null || createFarm.isPending || tooRough !== null}>
            Save farm
          </Button>
        </View>
      </KeyboardSpace>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: space.lg, gap: space.md },
  helper: { minHeight: 24 },
  fix: {
    marginTop: space.md,
    borderRadius: radius.md,
    padding: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
  },
  read: { marginTop: space.md },
  rough: { borderRadius: radius.lg, padding: space.lg, gap: space.sm },
  roughTitle: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  tip: { flexDirection: 'row', gap: space.sm },
  footer: {
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    gap: space.sm,
  },
});
