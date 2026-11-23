import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { focusManager, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useFonts } from 'expo-font';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import * as SystemUI from 'expo-system-ui';
import { useEffect, type ComponentProps } from 'react';
import { AppState, Platform, useColorScheme } from 'react-native';
import { PaperProvider } from 'react-native-paper';

import { ApiError } from '@/api';
import { useMe } from '@/api/queries';
import { useStoreHydrated } from '@/lib/hooks';
import { useCart } from '@/state/cart';
import { useDeliveryLocation } from '@/state/deliveryLocation';
import { usePreferences } from '@/state/preferences';
import { useSession } from '@/state/session';
import { darkTheme, lightTheme } from '@/theme';
import { fontAssets } from '@/theme/typography';

SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // One more try for a dropped connection or a server hiccup; a refusal (4xx) will not change by asking again.
      retry: (failures, error) =>
        failures < 1 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
    },
  },
});

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

const paperSettings = {
  icon: ({ name, color, size }: { name: string; color?: string; size: number }) => (
    <MaterialCommunityIcons name={name as IconName} color={color} size={size} />
  ),
};

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({ ...fontAssets, ...MaterialCommunityIcons.font });
  const storesReady = [
    useStoreHydrated(useSession),
    useStoreHydrated(useCart),
    useStoreHydrated(useDeliveryLocation),
    useStoreHydrated(usePreferences),
  ].every(Boolean);
  const ready = (fontsLoaded || fontError !== null) && storesReady;

  const systemScheme = useColorScheme();
  const themeMode = usePreferences((state) => state.themeMode);
  const dark = themeMode === 'system' ? systemScheme === 'dark' : themeMode === 'dark';
  const theme = dark ? darkTheme : lightTheme;
  const background = theme.colors.background;

  useEffect(() => {
    if (ready) SplashScreen.hideAsync();
  }, [ready]);

  useEffect(() => {
    SystemUI.setBackgroundColorAsync(background);
  }, [background]);

  useEffect(() => {
    // Tell TanStack Query when the app comes back to the front, so stale data is refreshed. Browsers do this themselves.
    if (Platform.OS === 'web') return undefined;
    const subscription = AppState.addEventListener('change', (status) => focusManager.setFocused(status === 'active'));
    return () => subscription.remove();
  }, []);

  useEffect(
    () =>
      // Whoever signs in next must not see the last person's orders.
      useSession.subscribe((state, previous) => {
        if (previous.user !== null && state.user === null) queryClient.clear();
      }),
    [],
  );

  if (!ready) return null;

  const base = dark ? DarkTheme : DefaultTheme;
  const navigationTheme = {
    ...base,
    colors: {
      ...base.colors,
      primary: theme.colors.primary,
      background,
      card: theme.colors.background,
      text: theme.colors.onBackground,
      border: theme.colors.outlineVariant,
    },
  };

  return (
    <QueryClientProvider client={queryClient}>
      <PaperProvider theme={theme} settings={paperSettings}>
        <ThemeProvider value={navigationTheme}>
          <StatusBar style={dark ? 'light' : 'dark'} />
          <RootNavigator />
        </ThemeProvider>
      </PaperProvider>
    </QueryClientProvider>
  );
}

/** The signed-in user's role decides which part of the app exists; the rest cannot be navigated to. */
function RootNavigator() {
  const role = useSession((state) => state.user?.role ?? null);
  const signOut = useSession((state) => state.signOut);
  const { error } = useMe();

  useEffect(() => {
    // The server no longer knows this session: back to sign-in.
    if (error instanceof ApiError && error.status === 401) signOut();
  }, [error, signOut]);

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Protected guard={role === null}>
        <Stack.Screen name="(auth)" />
      </Stack.Protected>
      <Stack.Protected guard={role === 'customer'}>
        <Stack.Screen name="(customer)" />
      </Stack.Protected>
      <Stack.Protected guard={role === 'farmer'}>
        <Stack.Screen name="farmer" />
      </Stack.Protected>
      <Stack.Protected guard={role === 'agent'}>
        <Stack.Screen name="agent" />
      </Stack.Protected>
      <Stack.Protected guard={role === 'farmer' || role === 'agent'}>
        <Stack.Screen name="account" />
      </Stack.Protected>
    </Stack>
  );
}
