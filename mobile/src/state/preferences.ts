import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type ThemeMode = 'system' | 'light' | 'dark';

interface PreferencesState {
  themeMode: ThemeMode;
  setThemeMode: (themeMode: ThemeMode) => void;
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      themeMode: 'system',
      setThemeMode: (themeMode) => set({ themeMode }),
    }),
    {
      name: 'f2h.preferences',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: ({ themeMode }) => ({ themeMode }),
    },
  ),
);
