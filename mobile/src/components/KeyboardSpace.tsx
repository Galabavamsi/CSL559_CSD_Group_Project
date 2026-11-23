import { createContext, useContext, useEffect, useRef, useState, type ComponentRef, type ReactNode } from 'react';
import {
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
  type ScrollViewProps,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

/** Room left between the field being typed in and the top of the keyboard. */
const GAP = 28;

/**
 * What has to be added to the keyboard's height as React Native reports it: how far down the screen the nearest
 * KeyboardSpace starts and, on Android, the height of the system's navigation bar.
 */
const Extra = createContext(0);

/**
 * Keeps a screen's fields above the on-screen keyboard. Put the screen's scrolling part in a KeyboardScroll.
 *
 * Android apps built with Expo are edge-to-edge: the window no longer shrinks when the keyboard opens, so a field in
 * the lower half of the screen ends up behind it. This view pads itself by the keyboard's height instead, on
 * Android as on iOS.
 *
 * Two corrections are needed, both seen on the phone. The padding is worked out from where this view sits, and
 * React Native takes that position relative to its parent: under a status bar or a top bar it is short by their
 * height, so the view measures where it really starts on the screen. And on Android the keyboard's height comes
 * without the navigation bar under it, which an edge-to-edge app draws behind, so that is added too.
 *
 * Found on a real phone (Android 16), where the sign-in field was typed into blind; a browser has no on-screen
 * keyboard and never showed it.
 */
export function KeyboardSpace({ children }: { children: ReactNode }) {
  const frame = useRef<ComponentRef<typeof View>>(null);
  const [top, setTop] = useState(0);
  const insets = useSafeAreaInsets();
  const extra = top + (Platform.OS === 'android' ? insets.bottom : 0);
  return (
    <View
      ref={frame}
      style={styles.fill}
      onLayout={() => frame.current?.measureInWindow((_x, y) => setTop(Math.max(0, Math.round(y))))}>
      <Extra.Provider value={extra}>
        <KeyboardAvoidingView style={styles.fill} behavior="padding" keyboardVerticalOffset={extra}>
          {children}
        </KeyboardAvoidingView>
      </Extra.Provider>
    </View>
  );
}

/**
 * The scrolling part of a screen with fields, at the top of a KeyboardSpace. Making room for the keyboard is not
 * enough: left to itself the list scrolls only until the top edge of the field shows, and the text stays hidden.
 * When the keyboard has opened, this scrolls the field in use to sit just above it.
 */
export function KeyboardScroll(props: ScrollViewProps) {
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const extra = useContext(Extra);
  useEffect(() => {
    const shown = Keyboard.addListener('keyboardDidShow', () => {
      const field = TextInput.State.currentlyFocusedInput();
      // The scroll is worked out from the same keyboard height, so it needs the same corrections.
      if (field) scroll.current?.scrollResponderScrollNativeHandleToKeyboard(field, extra + GAP, true);
    });
    return () => shown.remove();
  }, [extra]);
  return <ScrollView ref={scroll} keyboardShouldPersistTaps="handled" {...props} />;
}

const styles = StyleSheet.create({ fill: { flex: 1 } });
