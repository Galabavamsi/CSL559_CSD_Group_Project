import type { Grade } from '@/api';
import { daysFromToday, shortDay } from '@/lib/dates';

/** "Picked today", "Picked yesterday", "Picked 3 days ago"; null when the harvest date is unknown. */
export function pickedLabel(harvestDate: string | null): string | null {
  if (!harvestDate) return null;
  const daysAgo = -daysFromToday(harvestDate);
  if (daysAgo <= 0) return 'Picked today';
  if (daysAgo === 1) return 'Picked yesterday';
  return `Picked ${daysAgo} days ago`;
}

/** A date this far off gets its year: sugar that keeps a year would otherwise read "Use by 24 Nov" on 24 November. */
const SAY_THE_YEAR_AFTER_DAYS = 300;

/**
 * "Use by today", "Use by tomorrow", "Use by Fri", "Use by 4 Dec", "Use by 24 Nov 2027"; null when the date is
 * unknown.
 */
export function useByLabel(useByDate: string | null): string | null {
  if (!useByDate) return null;
  const days = daysFromToday(useByDate);
  if (days <= 0) return 'Use by today';
  if (days === 1) return 'Use by tomorrow';
  const year = days > SAY_THE_YEAR_AFTER_DAYS ? ` ${useByDate.slice(0, 4)}` : '';
  return `Use by ${shortDay(useByDate)}${year}`;
}

export const GRADE_EXPLANATION: Record<Grade, { title: string; body: string }> = {
  A: {
    title: 'Grade A',
    body: 'Even size and colour, firm, no marks. The hub checks every batch by hand before it is packed.',
  },
  B: {
    title: 'Grade B',
    body: 'Just as fresh and good to eat, but uneven in shape or size, or with small skin marks. Priced lower for that.',
  },
};
