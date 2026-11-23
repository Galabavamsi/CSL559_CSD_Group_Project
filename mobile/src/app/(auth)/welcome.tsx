import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState, type ComponentProps } from 'react';
import { StyleSheet, View } from 'react-native';
import { HelperText, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, isApiError, retryAfterSeconds, type Role } from '@/api';
import { MOCK_OTP_CODE } from '@/api/mock/data';
import { useRequestOtp } from '@/api/queries';
import { Logo } from '@/components/brand/Logo';
import { Wordmark } from '@/components/brand/Wordmark';
import { Button } from '@/components/Button';
import { DemoNote } from '@/components/DemoNote';
import { Screen } from '@/components/Screen';
import { Segmented, type SegmentOption } from '@/components/Segmented';
import { TextField } from '@/components/TextField';
import { usePendingSignIn } from '@/state/pendingSignIn';
import { radius, space, useAppTheme } from '@/theme';
import { KeyboardScroll, KeyboardSpace } from '@/components/KeyboardSpace';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

const PROMISES: { icon: IconName; text: string }[] = [
  { icon: 'sprout', text: 'Picked this week by farmers around your city' },
  { icon: 'check-decagram', text: 'Graded and packed at a hub near you' },
  { icon: 'account-group-outline', text: "Delivered together with your neighbours' orders" },
];

const ROLES: SegmentOption<Role>[] = [
  { value: 'customer', label: 'Customer' },
  { value: 'farmer', label: 'Farmer' },
  { value: 'agent', label: 'Delivery' },
];

const EMAIL = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

export default function Welcome() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const requestOtp = useRequestOtp();
  const beginSignIn = usePendingSignIn((state) => state.begin);

  const [role, setRole] = useState<Role>('customer');
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState<string | null>(null);

  const submit = () => {
    const address = email.trim().toLowerCase();
    if (!EMAIL.test(address)) {
      setEmailError('Enter your email address, for example asha@example.com');
      return;
    }
    setEmailError(null);
    const openCodeScreen = (waitSeconds: number) => {
      beginSignIn(address, role, waitSeconds);
      router.push('/verify');
    };

    requestOtp.mutate(
      { email: address, role },
      {
        onSuccess: (result) => openCodeScreen(result.retryAfterSeconds),
        onError: (error) => {
          // A code is already on its way to this address: go and enter it.
          if (isApiError(error, 'too_soon')) openCodeScreen(retryAfterSeconds(error) ?? 60);
        },
      },
    );
  };

  const requestError = requestOtp.error && !isApiError(requestOtp.error, 'too_soon') ? requestOtp.error : null;

  return (
    <Screen padTop>
      <KeyboardSpace>
        <KeyboardScroll
          contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + space.xl }]}
          keyboardShouldPersistTaps="handled">
          <View style={styles.brand}>
            <Logo size={52} />
            <Wordmark size={30} />
          </View>

          <Text variant="headlineMedium" style={styles.headline}>
            Fresh from nearby farms, at your door
          </Text>

          <View style={styles.promises}>
            {PROMISES.map((promise) => (
              <View key={promise.icon} style={styles.promise}>
                <View style={[styles.promiseIcon, { backgroundColor: colors.primaryContainer }]}>
                  <MaterialCommunityIcons name={promise.icon} size={20} color={colors.onPrimaryContainer} />
                </View>
                <Text variant="bodyMedium" style={[styles.flex, { color: colors.onSurfaceVariant }]}>
                  {promise.text}
                </Text>
              </View>
            ))}
          </View>

          <View style={[styles.card, { backgroundColor: colors.elevation.level1, borderColor: colors.outlineVariant }]}>
            <Text variant="titleMedium">Sign in or create an account</Text>
            <Text variant="bodySmall" style={[styles.cardHint, { color: colors.onSurfaceVariant }]}>
              We email you a 6-digit code. There is no password to remember.
            </Text>

            <Text variant="labelMedium" style={[styles.fieldLabel, { color: colors.onSurfaceVariant }]}>
              I am a
            </Text>
            <Segmented options={ROLES} value={role} onChange={setRole} accessibilityLabel="I am a" />

            <TextField
              label="Email address"
              value={email}
              onChangeText={(text) => {
                setEmail(text);
                setEmailError(null);
              }}
              onSubmitEditing={submit}
              error={emailError !== null || isApiError(requestOtp.error, 'bad_email')}
              keyboardType="email-address"
              inputMode="email"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="email"
              textContentType="emailAddress"
              returnKeyType="send"
              left={<TextField.Icon icon="email-outline" accessible={false} />}
              style={styles.input}
            />
            <HelperText type="error" visible={emailError !== null || requestError !== null} style={styles.helper}>
              {emailError ?? (requestError ? errorMessage(requestError) : ' ')}
            </HelperText>

            <Button mode="contained" onPress={submit} loading={requestOtp.isPending} disabled={requestOtp.isPending}>
              Send sign-in code
            </Button>
          </View>

          <View style={styles.demo}>
            <DemoNote>{`Demo data: no email is sent. Any address works, and the code is ${MOCK_OTP_CODE}.`}</DemoNote>
          </View>
        </KeyboardScroll>
      </KeyboardSpace>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { flexGrow: 1, paddingHorizontal: space.xl, paddingTop: space.xl },
  brand: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  headline: { marginTop: space.xl },
  promises: { marginTop: space.lg, gap: space.md },
  promise: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  promiseIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  card: {
    marginTop: space.xl,
    borderRadius: radius.xl,
    borderWidth: StyleSheet.hairlineWidth,
    padding: space.lg,
  },
  cardHint: { marginTop: space.xs },
  fieldLabel: { marginTop: space.lg, marginBottom: space.sm },
  input: { marginTop: space.lg },
  helper: { minHeight: 28 },
  demo: { marginTop: space.lg },
});
