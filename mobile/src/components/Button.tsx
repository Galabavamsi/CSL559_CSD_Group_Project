import type { ComponentProps } from 'react';
import { StyleSheet } from 'react-native';
import { Button as PaperButton } from 'react-native-paper';

import { TOUCH_TARGET } from '@/theme';

/** The Material button, always at least 48 dp tall so it is easy to hit. */
export function Button({ contentStyle, ...props }: ComponentProps<typeof PaperButton>) {
  return <PaperButton {...props} contentStyle={[styles.content, contentStyle]} />;
}

const styles = StyleSheet.create({
  content: { minHeight: TOUCH_TARGET },
});
