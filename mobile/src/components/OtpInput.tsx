import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';
import { Text } from 'react-native-paper';

import { fontFamily, radius, space, tabularNumbers, useAppTheme } from '@/theme';

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  length?: number;
  hasError?: boolean;
  disabled?: boolean;
}

/**
 * A code field drawn as one box per digit. A single invisible text input sits on top of the boxes, so typing,
 * pasting and the keyboard's "code from your messages" suggestion all behave like a normal field.
 */
export function OtpInput({ value, onChange, length = 6, hasError = false, disabled = false }: OtpInputProps) {
  const { colors } = useAppTheme();
  const [focused, setFocused] = useState(false);

  return (
    <View style={styles.row}>
      {Array.from({ length }, (_, index) => {
        const active = focused && index === Math.min(value.length, length - 1);
        const borderColor = hasError ? colors.error : active ? colors.primary : colors.outline;
        return (
          <View
            key={index}
            style={[
              styles.cell,
              { borderColor, backgroundColor: colors.elevation.level1, borderWidth: active || hasError ? 2 : 1 },
            ]}>
            <Text style={[styles.digit, tabularNumbers, { color: colors.onSurface }]}>{value[index] ?? ''}</Text>
          </View>
        );
      })}
      <TextInput
        value={value}
        onChangeText={(text) => onChange(text.replace(/\D/g, '').slice(0, length))}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        editable={!disabled}
        autoFocus
        keyboardType="number-pad"
        inputMode="numeric"
        autoComplete="one-time-code"
        textContentType="oneTimeCode"
        maxLength={length}
        caretHidden
        accessibilityLabel={`${length}-digit sign-in code`}
        style={[StyleSheet.absoluteFill, styles.input]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', gap: space.sm },
  cell: {
    flex: 1,
    maxWidth: 56,
    height: 60,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  digit: { fontFamily: fontFamily.bold, fontSize: 26, lineHeight: 32 },
  // Covers the boxes and takes the taps; its own text is never seen.
  input: { opacity: 0, fontSize: 16 },
});
