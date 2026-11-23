import { API_URL } from '@/config';

import type { ApiClient } from './client';
import { createHttpClient } from './http';
import { createMockClient } from './mock/client';

/** The one API client of this run, chosen at start-up: the real API when a URL is configured, else the mock. */
export const api: ApiClient = API_URL ? createHttpClient(API_URL) : createMockClient();

export type { ApiClient } from './client';
export * from './errors';
export * from './types';
