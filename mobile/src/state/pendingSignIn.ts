import { create } from 'zustand';

import type { Role } from '@/api/types';

interface PendingSignInState {
  /** The address a code was sent to; null when no sign-in is under way. */
  email: string | null;
  role: Role;
  /** When a new code may be asked for, in milliseconds since 1970. */
  resendAt: number;
  begin: (email: string, role: Role, waitSeconds: number) => void;
  /** After asking for another code, or being told to wait. */
  waitFor: (waitSeconds: number) => void;
}

/**
 * The sign-in that is waiting for its code. Held in memory and handed from the email screen to the code screen
 * this way, not as route parameters, so the address never appears in a URL on the web build.
 */
export const usePendingSignIn = create<PendingSignInState>()((set) => ({
  email: null,
  role: 'customer',
  resendAt: 0,
  begin: (email, role, waitSeconds) => set({ email, role, resendAt: Date.now() + waitSeconds * 1000 }),
  waitFor: (waitSeconds) => set({ resendAt: Date.now() + waitSeconds * 1000 }),
}));
