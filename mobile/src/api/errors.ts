/**
 * The one error type every API client throws.
 * `message` is written for the person using the app; `code` is for the app's own decisions.
 */
export class ApiError extends Error {
  readonly code: string;
  /** HTTP status, or 0 when no answer arrived. */
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code);
}

/** Words to show for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}

/** Seconds the API asked us to wait, when it said so (429 answers to a code request). */
export function retryAfterSeconds(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const seconds = error.details.retry_after_seconds;
  return typeof seconds === 'number' && seconds > 0 ? seconds : null;
}
