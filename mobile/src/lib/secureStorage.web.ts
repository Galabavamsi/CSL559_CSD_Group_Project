import type { StateStorage } from 'zustand/middleware';

/**
 * Web fallback for the session store. expo-secure-store has no web implementation, so the browser build keeps the
 * session in localStorage, which any script on the page can read. Fine for the demo build; a production web app
 * would use an HttpOnly cookie instead.
 */
export const secureStorage: StateStorage = {
  getItem: (key) => {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null; // storage is blocked (private window): start signed out
    }
  },
  setItem: (key, value) => {
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // storage is blocked: the session lasts until the tab closes
    }
  },
  removeItem: (key) => {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // nothing was stored
    }
  },
};
