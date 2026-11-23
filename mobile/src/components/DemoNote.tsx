import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { api } from '@/api';
import { radius, space, useAppTheme } from '@/theme';

/** A note that only shows when the app runs on demo data, so nobody mistakes the demo for the real thing. */
export function DemoNote({ children }: { children: string }) {
  const { colors } = useAppTheme();
  if (api.mode !== 'mock') return null;
  return (
    <View style={[styles.note, { backgroundColor: colors.secondaryContainer }]}>
      <MaterialCommunityIcons name="information-outline" size={18} color={colors.onSecondaryContainer} />
      <Text variant="bodySmall" style={[styles.text, { color: colors.onSecondaryContainer }]}>
        {children}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  note: {
    borderRadius: radius.md,
    padding: space.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
  },
  text: { flex: 1 },
});
