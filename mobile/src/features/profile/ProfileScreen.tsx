import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { HelperText, Snackbar, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api, errorMessage, isApiError, type Role } from '@/api';
import { useCities, useUpdateProfile } from '@/api/queries';
import { Button } from '@/components/Button';
import { Card } from '@/components/Card';
import { Segmented, type SegmentOption } from '@/components/Segmented';
import { TextField } from '@/components/TextField';
import { API_URL } from '@/config';
import { useDeliveryLocation } from '@/state/deliveryLocation';
import { usePreferences, type ThemeMode } from '@/state/preferences';
import { useSession } from '@/state/session';
import { fontFamily, radius, space, useAppTheme } from '@/theme';

import { useSignOut } from './useSignOut';

const ROLE_LABEL: Record<Role, string> = { customer: 'Customer', farmer: 'Farmer', agent: 'Delivery agent' };

const THEME_MODES: SegmentOption<ThemeMode>[] = [
  { value: 'system', label: 'System', icon: 'theme-light-dark' },
  { value: 'light', label: 'Light', icon: 'white-balance-sunny' },
  { value: 'dark', label: 'Dark', icon: 'moon-waning-crescent' },
];

/** Name, phone and city; light or dark; sign out. The same screen for every role. */
export function ProfileScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();

  const user = useSession((state) => state.user);
  const location = useDeliveryLocation((state) => state.location);
  const themeMode = usePreferences((state) => state.themeMode);
  const setThemeMode = usePreferences((state) => state.setThemeMode);
  const cities = useCities();
  const updateProfile = useUpdateProfile();
  const signOut = useSignOut();

  const [name, setName] = useState(user?.name ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [city, setCity] = useState(user?.city ?? null);
  const [saved, setSaved] = useState(false);

  if (!user) return null; // signing out: the sign-in screen is about to replace this one

  const changed =
    name.trim() !== (user.name ?? '') || phone.trim() !== (user.phone ?? '') || city !== (user.city ?? null);
  const phoneError = isApiError(updateProfile.error, 'bad_phone');
  const otherError = updateProfile.isError && !phoneError;

  const save = () =>
    updateProfile.mutate(
      { name: name.trim() || null, phone: phone.trim() || null, city },
      { onSuccess: () => setSaved(true) },
    );

  const initial = (user.name ?? user.email).trim().charAt(0).toUpperCase();

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView
        contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + space.xl }]}
        keyboardShouldPersistTaps="handled">
        <View style={styles.identity}>
          <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
            <Text style={[styles.avatarText, { color: colors.onPrimary }]}>{initial}</Text>
          </View>
          <View style={styles.flex}>
            <Text variant="titleLarge" numberOfLines={1}>
              {user.name ?? 'Welcome'}
            </Text>
            <Text variant="bodyMedium" numberOfLines={1} style={{ color: colors.onSurfaceVariant }}>
              {user.email}
            </Text>
            <View style={[styles.role, { backgroundColor: colors.secondaryContainer }]}>
              <Text variant="labelSmall" style={{ color: colors.onSecondaryContainer }}>
                {ROLE_LABEL[user.role]}
              </Text>
            </View>
          </View>
        </View>

        <Card title="Your details">
          <TextField
            label="Name"
            value={name}
            onChangeText={setName}
            autoComplete="name"
            textContentType="name"
            maxLength={80}
          />
          <TextField
            label="Phone"
            value={phone}
            onChangeText={setPhone}
            error={phoneError}
            keyboardType="phone-pad"
            inputMode="tel"
            autoComplete="tel"
            textContentType="telephoneNumber"
            maxLength={24}
            style={styles.field}
          />
          <HelperText type="error" visible={phoneError} style={styles.helper}>
            {phoneError ? errorMessage(updateProfile.error) : ' '}
          </HelperText>

          <Text variant="labelMedium" style={[styles.label, { color: colors.onSurfaceVariant }]}>
            City
          </Text>
          {cities.data ? (
            <Segmented
              options={cities.data.map((option) => ({ value: option.slug, label: option.name }))}
              value={city}
              onChange={setCity}
              accessibilityLabel="City"
            />
          ) : (
            <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
              {cities.isError ? 'The list of cities could not be loaded.' : 'Loading cities'}
            </Text>
          )}

          {otherError ? (
            <Text variant="bodySmall" accessibilityRole="alert" style={[styles.error, { color: colors.error }]}>
              {errorMessage(updateProfile.error)}
            </Text>
          ) : null}
          <Button
            mode="contained"
            onPress={save}
            loading={updateProfile.isPending}
            disabled={!changed || updateProfile.isPending}
            style={styles.save}>
            Save changes
          </Button>
        </Card>

        {user.role === 'customer' && location ? (
          <Card title="Delivery location">
            <View style={styles.rowBetween}>
              <MaterialCommunityIcons name="map-marker" size={22} color={colors.primary} />
              <View style={styles.flex}>
                <Text variant="bodyLarge" numberOfLines={1}>
                  {location.label}
                </Text>
                <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
                  Served by {location.hubName}
                </Text>
              </View>
              <Button mode="text" compact onPress={() => router.push('/location')}>
                Change
              </Button>
            </View>
          </Card>
        ) : null}

        <Card title="Appearance">
          <Segmented options={THEME_MODES} value={themeMode} onChange={setThemeMode} accessibilityLabel="Theme" />
        </Card>

        <View style={[styles.source, { backgroundColor: colors.surfaceVariant }]}>
          <MaterialCommunityIcons name="information-outline" size={18} color={colors.onSurfaceVariant} />
          <Text variant="bodySmall" style={[styles.flex, { color: colors.onSurfaceVariant }]}>
            {api.mode === 'mock'
              ? 'Running on demo data. Nothing you do here reaches a real hub.'
              : `Connected to ${API_URL}`}
          </Text>
        </View>

        <Button
          mode="outlined"
          icon="logout"
          textColor={colors.error}
          onPress={() => signOut.mutate()}
          loading={signOut.isPending}
          disabled={signOut.isPending}>
          Sign out
        </Button>
      </ScrollView>

      <Snackbar visible={saved} onDismiss={() => setSaved(false)} duration={2500}>
        Profile saved
      </Snackbar>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: space.lg, gap: space.md },
  identity: { flexDirection: 'row', alignItems: 'center', gap: space.lg, marginBottom: space.sm },
  avatar: { width: 64, height: 64, borderRadius: 32, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontFamily: fontFamily.extraBold, fontSize: 28, lineHeight: 34 },
  role: { alignSelf: 'flex-start', borderRadius: radius.sm, paddingHorizontal: 8, paddingVertical: 2, marginTop: 4 },
  field: { marginTop: space.md },
  helper: { minHeight: 24 },
  label: { marginBottom: space.sm },
  error: { marginTop: space.md },
  save: { marginTop: space.lg },
  rowBetween: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  source: {
    borderRadius: radius.md,
    padding: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
  },
});
