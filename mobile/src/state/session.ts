import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import type { AuthSession, User } from '@/api/types';
import { storageName } from '@/config';
import { secureStorage } from '@/lib/secureStorage';

interface SessionState {
  accessToken: string | null;
  /** When the access token stops working, in milliseconds since 1970; null when the API did not say. */
  accessTokenExpiresAt: number | null;
  refreshToken: string | null;
  user: User | null;
  signIn: (session: AuthSession) => void;
  /** After the API exchanged the refresh token for a new pair. */
  renew: (session: Pick<AuthSession, 'accessToken' | 'refreshToken' | 'expiresInSeconds'>) => void;
  setUser: (user: User) => void;
  signOut: () => void;
}

function expiryOf(expiresInSeconds: number | null): number | null {
  return expiresInSeconds === null ? null : Date.now() + expiresInSeconds * 1000;
}

/**
 * Who is signed in. On a phone both tokens are kept in secure storage (Android Keystore / iOS Keychain), so a
 * restart does not ask for a new code.
 */
export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      accessToken: null,
      accessTokenExpiresAt: null,
      refreshToken: null,
      user: null,
      signIn: (session) =>
        set({
          accessToken: session.accessToken,
          accessTokenExpiresAt: expiryOf(session.expiresInSeconds),
          refreshToken: session.refreshToken,
          user: session.user,
        }),
      renew: (session) =>
        set({
          accessToken: session.accessToken,
          accessTokenExpiresAt: expiryOf(session.expiresInSeconds),
          refreshToken: session.refreshToken,
        }),
      setUser: (user) => set({ user }),
      signOut: () => set({ accessToken: null, accessTokenExpiresAt: null, refreshToken: null, user: null }),
    }),
    {
      name: storageName('f2h.session'),
      storage: createJSONStorage(() => secureStorage),
      partialize: ({ accessToken, accessTokenExpiresAt, refreshToken, user }) => ({
        accessToken,
        accessTokenExpiresAt,
        refreshToken,
        user,
      }),
    },
  ),
);
