import { useRouter } from 'expo-router';
import { StyleSheet, View } from 'react-native';
import { IconButton, Text } from 'react-native-paper';

import { useSession } from '@/state/session';
import { space, TOUCH_TARGET, useAppTheme } from '@/theme';

import { Logo } from './brand/Logo';
import { Wordmark } from './brand/Wordmark';

/** Top of the farmer's and the delivery agent's home: the brand, who is signed in, and the way to the account. */
export function RoleHeader({ roleLabel }: { roleLabel: string }) {
  const router = useRouter();
  const { colors } = useAppTheme();
  const user = useSession((state) => state.user);

  return (
    <View style={styles.header}>
      <Logo size={40} />
      <View style={styles.text}>
        <Wordmark size={22} />
        <Text variant="bodySmall" numberOfLines={1} style={{ color: colors.onSurfaceVariant }}>
          {roleLabel} · {user?.name ?? user?.email ?? ''}
        </Text>
      </View>
      <IconButton
        icon="account-circle-outline"
        size={28}
        onPress={() => router.push('/account')}
        accessibilityLabel="Account and settings"
        style={styles.action}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingLeft: space.lg,
    paddingRight: space.sm,
    paddingVertical: space.sm,
  },
  text: { flex: 1 },
  action: { width: TOUCH_TARGET, height: TOUCH_TARGET, margin: 0 },
});
