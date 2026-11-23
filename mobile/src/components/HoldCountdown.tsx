import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { StyleSheet, View } from 'react-native';
import { Text } from 'react-native-paper';

import { formatClock, formatTime, secondsUntil } from '@/lib/dates';
import type { ActiveHold } from '@/state/cart';
import { fontFamily, radius, space, useAppTheme } from '@/theme';

/** Below this many seconds the countdown turns from green to the warm accent. */
const HURRY_SECONDS = 120;

interface ClockProps {
  seconds: number;
  size: number;
  color: string;
}

/**
 * A mm:ss clock whose characters each sit in a cell of fixed width, so the text does not shift as digits change
 * (a 1 is narrower than an 8 in most typefaces).
 */
export function Clock({ seconds, size, color }: ClockProps) {
  const text = formatClock(seconds);
  return (
    <View
      style={styles.clock}
      accessible
      accessibilityRole="timer"
      accessibilityLabel={`${Math.floor(seconds / 60)} minutes ${Math.ceil(seconds) % 60} seconds left`}>
      {text.split('').map((character, index) => (
        <Text
          key={index}
          style={{
            width: size * (character === ':' ? 0.34 : 0.66),
            textAlign: 'center',
            fontFamily: fontFamily.extraBold,
            fontSize: size,
            lineHeight: Math.round(size * 1.2),
            color,
          }}>
          {character}
        </Text>
      ))}
    </View>
  );
}

interface HoldCountdownProps {
  hold: ActiveHold;
  hubName: string;
  /** Current time in milliseconds, from `useNow`. */
  now: number;
}

/** The checkout's main card: how long the stock stays set aside, as a clock and a bar that runs down. */
export function HoldCountdown({ hold, hubName, now }: HoldCountdownProps) {
  const { colors, brand } = useAppTheme();
  const remaining = secondsUntil(hold.expiresAt, now);
  const total = Math.max(1, (new Date(hold.expiresAt).getTime() - new Date(hold.heldAt).getTime()) / 1000);
  const hurry = remaining <= HURRY_SECONDS;
  const background = hurry ? brand.mangoContainer : colors.primaryContainer;
  const ink = hurry ? brand.onMangoContainer : colors.onPrimaryContainer;

  return (
    <View style={[styles.card, { backgroundColor: background }]}>
      <View style={styles.top}>
        <MaterialCommunityIcons name="lock-clock" size={28} color={ink} />
        <View style={styles.text}>
          <Text variant="titleMedium" style={{ color: ink }}>
            {hurry ? 'Almost out of time' : 'Your items are held'}
          </Text>
          <Text variant="bodySmall" style={{ color: ink }}>
            {hubName} keeps them aside until {formatTime(hold.expiresAt)}
          </Text>
        </View>
        <Clock seconds={remaining} size={30} color={ink} />
      </View>
      <View style={[styles.track, { backgroundColor: colors.elevation.level1 }]}>
        <View
          style={[
            styles.fill,
            {
              width: `${Math.min(100, (remaining / total) * 100)}%`,
              backgroundColor: hurry ? colors.tertiary : colors.primary,
            },
          ]}
        />
      </View>
      <Text variant="bodySmall" style={{ color: ink }}>
        Pay before the clock runs out. After that the items go back on sale for everyone.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  clock: { flexDirection: 'row' },
  card: { borderRadius: radius.lg, padding: space.lg, gap: space.md },
  top: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  text: { flex: 1 },
  track: { height: 8, borderRadius: 4, overflow: 'hidden' },
  fill: { height: 8, borderRadius: 4 },
});
