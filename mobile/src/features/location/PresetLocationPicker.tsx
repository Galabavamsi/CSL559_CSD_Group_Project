import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import * as Location from 'expo-location';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { HelperText, Text } from 'react-native-paper';

import { Button } from '@/components/Button';
import { Segmented } from '@/components/Segmented';
import { radius, space, useAppTheme } from '@/theme';

import type { LocationPickerProps } from './LocationPicker';
import { presetAreasOf } from './presetAreas';

const CURRENT_LOCATION_LABEL = 'Current location';

/** Location picking without a map: the phone's GPS, or a named area of the chosen city. */
export function PresetLocationPicker({ cities, initialCitySlug, value, onChange }: LocationPickerProps) {
  const { colors } = useAppTheme();
  const [citySlug, setCitySlug] = useState(
    () => cities.find((city) => city.slug === initialCitySlug)?.slug ?? cities[0]?.slug ?? null,
  );
  const [locating, setLocating] = useState(false);
  const [gpsError, setGpsError] = useState<string | null>(null);

  const city = cities.find((candidate) => candidate.slug === citySlug) ?? null;
  const usingGps = value?.label === CURRENT_LOCATION_LABEL;

  const locateMe = async () => {
    setLocating(true);
    setGpsError(null);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (!permission.granted) {
        setGpsError('Location access is off. Pick your area from the list instead.');
        return;
      }
      const position = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      onChange({
        label: CURRENT_LOCATION_LABEL,
        lat: position.coords.latitude,
        lng: position.coords.longitude,
      });
    } catch {
      setGpsError('Could not find your location. Pick your area from the list instead.');
    } finally {
      setLocating(false);
    }
  };

  return (
    <View>
      <Button
        mode={usingGps ? 'contained' : 'contained-tonal'}
        icon="crosshairs-gps"
        onPress={locateMe}
        loading={locating}
        disabled={locating}>
        Use my current location
      </Button>
      <HelperText type="error" visible={gpsError !== null} style={styles.helper}>
        {gpsError ?? ' '}
      </HelperText>

      <Text variant="labelLarge" style={[styles.label, { color: colors.onSurfaceVariant }]}>
        Or pick your area
      </Text>
      {cities.length > 1 ? (
        <Segmented
          options={cities.map((option) => ({ value: option.slug, label: option.name }))}
          value={citySlug}
          onChange={setCitySlug}
          accessibilityLabel="City"
        />
      ) : null}

      {city ? (
        <View
          accessibilityRole="radiogroup"
          style={[styles.list, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
          {presetAreasOf(city).map((area, index) => {
            const label = `${area.name}, ${city.name}`;
            const selected = value?.label === label;
            return (
              <Pressable
                key={area.name}
                onPress={() => onChange({ label, lat: area.lat, lng: area.lng })}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                accessibilityLabel={label}
                android_ripple={{ color: colors.surfaceVariant }}
                style={[
                  styles.row,
                  index > 0 && { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.outlineVariant },
                  selected && { backgroundColor: colors.primaryContainer },
                ]}>
                <MaterialCommunityIcons
                  name={selected ? 'map-marker' : 'map-marker-outline'}
                  size={22}
                  color={selected ? colors.onPrimaryContainer : colors.onSurfaceVariant}
                />
                <Text
                  variant="bodyLarge"
                  style={[styles.rowText, { color: selected ? colors.onPrimaryContainer : colors.onSurface }]}>
                  {area.name}
                </Text>
                {selected ? <MaterialCommunityIcons name="check" size={20} color={colors.onPrimaryContainer} /> : null}
              </Pressable>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  helper: { minHeight: 24 },
  label: { marginTop: space.sm, marginBottom: space.sm },
  list: {
    marginTop: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  row: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
  },
  rowText: { flex: 1 },
});
