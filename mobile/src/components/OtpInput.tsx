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
  /** Open the keyboard as soon as the field shows. Right for a screen that is only about the code. */
  autoFocus?: boolean;
  /** Let the keyboard offer a code from a message that just arrived. Off for a code someone reads out. */
  fromMessages?: boolean;
  /** What the code is, for screen readers. */
  accessibilityLabel?: string;
}

/**
 * A code field drawn as one box per digit. A single invisible text input sits on top of the boxes, so typing,
 * pasting and the keyboard's "code from your messages" suggestion all behave like a normal field.
 */
export function OtpInput({
  value,
  onChange,
  length = 6,
  hasError = false,
  disabled = false,
  autoFocus = true,
  fromMessages = true,
  accessibilityLabel = `${length}-digit sign-in code`,
}: OtpInputProps) {
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
        autoFocus={autoFocus}
        keyboardType="number-pad"
        inputMode="numeric"
        autoComplete={fromMessages ? 'one-time-code' : 'off'}
        textContentType={fromMessages ? 'oneTimeCode' : 'none'}
        maxLength={length}
        caretHidden
        accessibilityLabel={accessibilityLabel}
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
