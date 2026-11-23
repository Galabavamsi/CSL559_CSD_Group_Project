import * as SecureStore from 'expo-secure-store';
import type { StateStorage } from 'zustand/middleware';

/** Where the session lives on a phone: the Android Keystore / iOS Keychain, through expo-secure-store. */
export const secureStorage: StateStorage = {
  getItem: (key) => SecureStore.getItemAsync(key),
  setItem: (key, value) => SecureStore.setItemAsync(key, value),
  removeItem: (key) => SecureStore.deleteItemAsync(key),
};
