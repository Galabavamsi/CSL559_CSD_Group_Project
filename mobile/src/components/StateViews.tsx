import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import type { ComponentProps, ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { errorMessage, isApiError } from '@/api';
import { space, useAppTheme } from '@/theme';

import { Button } from './Button';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

interface EmptyStateProps {
  icon: IconName;
  title: string;
  message: string;
  /** Usually one button. */
  children?: ReactNode;
}

/** Shown where a list would be when there is nothing to list. */
export function EmptyState({ icon, title, message, children }: EmptyStateProps) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.container}>
      <View style={[styles.iconRing, { backgroundColor: colors.primaryContainer }]}>
        <MaterialCommunityIcons name={icon} size={40} color={colors.onPrimaryContainer} />
      </View>
      <Text variant="titleLarge" style={styles.title}>
        {title}
      </Text>
      <Text variant="bodyMedium" style={[styles.message, { color: colors.onSurfaceVariant }]}>
        {message}
      </Text>
      {children && <View style={styles.actions}>{children}</View>}
    </View>
  );
}

interface ErrorStateProps {
  error: unknown;
  onRetry: () => void;
  retrying?: boolean;
}

/** Shown where content would be when loading it failed. Says what went wrong and offers another try. */
export function ErrorState({ error, onRetry, retrying = false }: ErrorStateProps) {
  const { colors } = useAppTheme();
  const offline = isApiError(error, 'network_error');
  return (
    <View style={styles.container} accessibilityRole="alert">
      <View style={[styles.iconRing, { backgroundColor: colors.errorContainer }]}>
        <MaterialCommunityIcons
          name={offline ? 'wifi-off' : 'alert-circle-outline'}
          size={40}
          color={colors.onErrorContainer}
        />
      </View>
      <Text variant="titleLarge" style={styles.title}>
        {offline ? 'No connection' : 'That did not load'}
      </Text>
      <Text variant="bodyMedium" style={[styles.message, { color: colors.onSurfaceVariant }]}>
        {errorMessage(error)}
      </Text>
      <View style={styles.actions}>
        <Button mode="contained-tonal" icon="refresh" onPress={onRetry} loading={retrying} disabled={retrying}>
          Try again
        </Button>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.xxl,
    paddingVertical: space.xxl,
  },
  iconRing: {
    width: 88,
    height: 88,
    borderRadius: 44,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.lg,
  },
  title: { textAlign: 'center' },
  message: { textAlign: 'center', marginTop: space.sm, maxWidth: 320 },
  actions: { marginTop: space.xl, alignSelf: 'stretch', alignItems: 'center', gap: space.sm },
});
