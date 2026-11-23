import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import type { BottomTabBarProps } from 'expo-router/tabs';
import { Pressable, StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import type { IconName } from '@/features/catalogue/categories';
import { fontFamily, MAX_CONTENT_WIDTH, radius, useAppTheme } from '@/theme';

/** Icon of each tab by route name: [when open, when not]. */
const TAB_ICONS: Record<string, [IconName, IconName]> = {
  home: ['storefront', 'storefront-outline'],
  orders: ['receipt-text', 'receipt-text-outline'],
  profile: ['account-circle', 'account-circle-outline'],
};

/** Material 3 navigation bar: an icon in a pill that fills when its tab is open, with the label under it. */
export function TabBar({ state, descriptors, emitter, navigateToTab, insets }: BottomTabBarProps) {
  const { colors } = useAppTheme();

  return (
    <View
      style={[
        styles.bar,
        {
          backgroundColor: colors.elevation.level2,
          borderTopColor: colors.outlineVariant,
          paddingBottom: insets.bottom,
          paddingLeft: insets.left,
          paddingRight: insets.right,
        },
      ]}>
      <View style={styles.row} accessibilityRole="tablist">
        {state.routes.map((route, index) => {
          const focused = state.index === index;
          const label = descriptors[route.key].options.title ?? route.name;
          const [openIcon, closedIcon] = TAB_ICONS[route.name] ?? ['circle', 'circle-outline'];

          const open = () => {
            const event = emitter.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
            if (!focused && !event.defaultPrevented) navigateToTab(route.key);
          };

          return (
            <Pressable
              key={route.key}
              onPress={open}
              accessibilityRole="tab"
              accessibilityState={{ selected: focused }}
              accessibilityLabel={label}
              style={styles.tab}>
              <View style={[styles.pill, focused && { backgroundColor: colors.secondaryContainer }]}>
                <MaterialCommunityIcons
                  name={focused ? openIcon : closedIcon}
                  size={24}
                  color={focused ? colors.onSecondaryContainer : colors.onSurfaceVariant}
                />
              </View>
              <Text
                variant="labelMedium"
                numberOfLines={1}
                style={{
                  color: focused ? colors.onSurface : colors.onSurfaceVariant,
                  fontFamily: focused ? fontFamily.bold : fontFamily.medium,
                }}>
                {label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { borderTopWidth: StyleSheet.hairlineWidth, alignItems: 'center' },
  row: { flexDirection: 'row', width: '100%', maxWidth: MAX_CONTENT_WIDTH },
  tab: { flex: 1, height: 72, alignItems: 'center', justifyContent: 'center', gap: 4 },
  pill: { width: 64, height: 32, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center' },
});
