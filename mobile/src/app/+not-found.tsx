import { useRouter } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Button } from '@/components/Button';
import { EmptyState } from '@/components/StateViews';
import { useAppTheme } from '@/theme';

export default function NotFound() {
  const router = useRouter();
  const { colors } = useAppTheme();
  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <EmptyState
        icon="map-search-outline"
        title="Nothing at this address"
        message="The page you opened does not exist, or you need to sign in to see it.">
        <Button mode="contained" onPress={() => router.replace('/')}>
          Go to the start
        </Button>
      </EmptyState>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
});
