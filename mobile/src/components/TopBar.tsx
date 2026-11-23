import { useRouter, type Href } from 'expo-router';
import type { ReactNode } from 'react';
import { StyleSheet } from 'react-native';
import { Appbar } from 'react-native-paper';

import { TOUCH_TARGET, useAppTheme } from '@/theme';

interface TopBarProps {
  title: string;
  /** Where "back" goes when there is no screen to go back to (a page opened directly on the web). */
  backFallback?: Href;
  /** Set to false on a screen that is the start of its flow. */
  showBack?: boolean;
  children?: ReactNode;
}

/** Screen header with a back button. Handles the status-bar inset itself. */
export function TopBar({ title, backFallback = '/', showBack = true, children }: TopBarProps) {
  const router = useRouter();
  const { colors } = useAppTheme();

  const goBack = () => {
    if (router.canGoBack()) router.back();
    else router.replace(backFallback);
  };

  return (
    <Appbar.Header mode="small" style={{ backgroundColor: colors.background }}>
      {showBack && <Appbar.BackAction onPress={goBack} accessibilityLabel="Go back" style={styles.action} />}
      <Appbar.Content title={title} titleStyle={styles.title} />
      {children}
    </Appbar.Header>
  );
}

const styles = StyleSheet.create({
  action: { width: TOUCH_TARGET, height: TOUCH_TARGET },
  title: { fontSize: 20, lineHeight: 28 },
});
