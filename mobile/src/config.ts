/**
 * Start-up configuration, read once from the environment.
 *
 * `EXPO_PUBLIC_API_URL` set   -> the app talks to that API over HTTP.
 * `EXPO_PUBLIC_API_URL` unset -> the app runs on the in-memory mock (demo data, nothing leaves the device).
 *
 * Expo inlines `process.env.EXPO_PUBLIC_*` at bundle time, so each variable must be written out in full here.
 */

function positiveNumber(raw: string | undefined, fallback: number): number {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

const rawApiUrl = process.env.EXPO_PUBLIC_API_URL?.trim() ?? '';

/** Base URL of the real API without a trailing slash, or null in mock mode. */
export const API_URL: string | null = rawApiUrl ? rawApiUrl.replace(/\/+$/, '') : null;

/** Mock only: how long a checkout hold lasts. The real API decides this itself (10 minutes). */
export const MOCK_HOLD_SECONDS = positiveNumber(process.env.EXPO_PUBLIC_MOCK_HOLD_SECONDS, 600);

/** Mock only: seconds between two order states, so the tracking screen can be watched moving. */
export const MOCK_ORDER_STEP_SECONDS = positiveNumber(process.env.EXPO_PUBLIC_MOCK_ORDER_STEP_SECONDS, 12);
