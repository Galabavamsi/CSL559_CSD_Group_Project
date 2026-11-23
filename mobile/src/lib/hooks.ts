import { useEffect, useState, useSyncExternalStore } from 'react';

/** The current time in milliseconds, refreshed every `intervalMs`. Drives countdowns. */
export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

interface PersistApi {
  hasHydrated: () => boolean;
  onFinishHydration: (listener: () => void) => () => void;
}

/** True once a persisted store has read its saved state back from storage. */
export function useStoreHydrated(store: { persist: PersistApi }): boolean {
  return useSyncExternalStore(store.persist.onFinishHydration, store.persist.hasHydrated, () => false);
}

/** `value`, but only after it has stayed the same for `delayMs`. Keeps search from filtering on every keystroke. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}
