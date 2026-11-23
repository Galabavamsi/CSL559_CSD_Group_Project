import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { IconName } from '@/features/catalogue/categories';
import { space, useAppTheme } from '@/theme';

export interface Step {
  icon: IconName;
  title: string;
  text: string;
}

/** A short "how it works" list: an icon, a title and one sentence per step. */
export function Steps({ steps }: { steps: Step[] }) {
  const { colors } = useAppTheme();
  return (
    <View style={styles.steps}>
      {steps.map((step) => (
        <View key={step.title} style={styles.step}>
          <View style={[styles.icon, { backgroundColor: colors.primaryContainer }]}>
            <MaterialCommunityIcons name={step.icon} size={20} color={colors.onPrimaryContainer} />
          </View>
          <View style={styles.text}>
            <Text variant="titleSmall">{step.title}</Text>
            <Text variant="bodySmall" style={{ color: colors.onSurfaceVariant }}>
              {step.text}
            </Text>
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  steps: { gap: space.lg },
  step: { flexDirection: 'row', gap: space.md },
  icon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1 },
});
