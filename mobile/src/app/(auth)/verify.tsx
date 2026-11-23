import { Redirect, useRouter } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { HelperText, Text } from 'react-native-paper';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { errorMessage, retryAfterSeconds } from '@/api';
import { MOCK_OTP_CODE } from '@/api/mock/data';
import { useRequestOtp, useVerifyOtp } from '@/api/queries';
import { Button } from '@/components/Button';
import { DemoNote } from '@/components/DemoNote';
import { OtpInput } from '@/components/OtpInput';
import { Screen } from '@/components/Screen';
import { TopBar } from '@/components/TopBar';
import { formatClock } from '@/lib/dates';
import { useNow } from '@/lib/hooks';
import { usePendingSignIn } from '@/state/pendingSignIn';
import { space, tabularNumbers, useAppTheme } from '@/theme';

const CODE_LENGTH = 6;

export default function Verify() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = useAppTheme();
  const email = usePendingSignIn((state) => state.email);
  const role = usePendingSignIn((state) => state.role);
  const resendAt = usePendingSignIn((state) => state.resendAt);
  const waitFor = usePendingSignIn((state) => state.waitFor);

  const verifyOtp = useVerifyOtp();
  const requestOtp = useRequestOtp();
  const [code, setCode] = useState('');
  const now = useNow();
  const waitSeconds = Math.max(0, Math.ceil((resendAt - now) / 1000));

  // Opened without asking for a code first (a reloaded web page): start again from the email.
  if (!email) return <Redirect href="/welcome" />;

  const verify = (entered: string) => {
    if (entered.length !== CODE_LENGTH || verifyOtp.isPending) return;
    verifyOtp.mutate({ email, code: entered }, { onSuccess: () => router.replace('/'), onError: () => setCode('') });
  };

  const changeCode = (next: string) => {
    setCode(next);
    if (next.length < CODE_LENGTH) return;
    verify(next); // the last digit sends the code; no extra tap needed
  };

  const resend = () => {
    verifyOtp.reset();
    setCode('');
    requestOtp.mutate(
      { email, role },
      {
        onSuccess: (result) => waitFor(result.retryAfterSeconds),
        onError: (error) => {
          // too_soon and too_many_codes say how long to wait before asking again.
          const wait = retryAfterSeconds(error);
          if (wait !== null) waitFor(wait);
        },
      },
    );
  };

  const error = verifyOtp.error ?? requestOtp.error;

  return (
    <Screen>
      <TopBar title="Enter your code" backFallback="/welcome" />
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          contentContainerStyle={[styles.content, { paddingBottom: insets.bottom + space.xl }]}
          keyboardShouldPersistTaps="handled">
          <Text variant="bodyLarge" style={{ color: colors.onSurfaceVariant }}>
            We sent a 6-digit code to
          </Text>
          <Text variant="titleMedium" numberOfLines={1}>
            {email}
          </Text>

          <View style={styles.code}>
            <OtpInput
              value={code}
              onChange={changeCode}
              length={CODE_LENGTH}
              hasError={verifyOtp.isError}
              disabled={verifyOtp.isPending}
            />
          </View>
          <HelperText type="error" visible={error !== null} style={styles.helper}>
            {error ? errorMessage(error) : ' '}
          </HelperText>

          <Button
            mode="contained"
            onPress={() => verify(code)}
            loading={verifyOtp.isPending}
            disabled={code.length !== CODE_LENGTH || verifyOtp.isPending}>
            Verify and continue
          </Button>

          <View style={styles.resend}>
            {waitSeconds > 0 ? (
              <Text
                variant="bodyMedium"
                accessibilityLabel={`You can ask for a new code in ${waitSeconds} seconds`}
                style={[styles.resendWait, tabularNumbers, { color: colors.onSurfaceVariant }]}>
                Resend code in {formatClock(waitSeconds)}
              </Text>
            ) : (
              <Button mode="text" onPress={resend} loading={requestOtp.isPending} disabled={requestOtp.isPending}>
                Resend code
              </Button>
            )}
          </View>

          <View style={styles.demo}>
            <DemoNote>{`Demo data: the code is ${MOCK_OTP_CODE}.`}</DemoNote>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { flexGrow: 1, paddingHorizontal: space.xl, paddingTop: space.md },
  code: { marginTop: space.xl },
  helper: { minHeight: 44 }, // room for a two-line message, so the button below does not move when one appears
  resend: { marginTop: space.sm, minHeight: 48, alignItems: 'center', justifyContent: 'center' },
  resendWait: { textAlign: 'center' },
  demo: { marginTop: space.lg },
});
