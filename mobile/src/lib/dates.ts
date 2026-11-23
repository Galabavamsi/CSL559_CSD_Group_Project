const DAY_MS = 86_400_000;
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

/** A calendar date (YYYY-MM-DD) as local midnight. */
function parseIsoDate(isoDate: string): Date {
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(year, month - 1, day);
}

/** The local calendar date `days` away from `from`, as YYYY-MM-DD. */
export function isoDateAfter(days: number, from: Date = new Date()): string {
  const date = new Date(from.getFullYear(), from.getMonth(), from.getDate() + days);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Whole calendar days from today to `isoDate`: 0 is today, 1 tomorrow, -1 yesterday. */
export function daysFromToday(isoDate: string, now: Date = new Date()): number {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((parseIsoDate(isoDate).getTime() - today.getTime()) / DAY_MS);
}

/** "Fri" for a date within the coming week, "4 Dec" beyond it. */
export function shortDay(isoDate: string, now: Date = new Date()): string {
  const date = parseIsoDate(isoDate);
  const days = daysFromToday(isoDate, now);
  return days >= 0 && days < 7 ? WEEKDAYS[date.getDay()] : `${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** "10:42 am" */
export function formatTime(iso: string): string {
  const date = new Date(iso);
  const hours = date.getHours();
  return `${hours % 12 || 12}:${pad(date.getMinutes())} ${hours < 12 ? 'am' : 'pm'}`;
}

/** "Mon 23 Nov, 10:42 am" */
export function formatDayTime(iso: string): string {
  const date = new Date(iso);
  return `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}, ${formatTime(iso)}`;
}

/** A calendar date (YYYY-MM-DD) as "Mon 23 Nov". */
export function formatDate(isoDate: string): string {
  const date = parseIsoDate(isoDate);
  return `${WEEKDAYS[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

/** A time window on one day, "Tue 24 Nov, 6:00 am to 9:00 am". */
export function formatSlot(fromIso: string, untilIso: string): string {
  return `${formatDayTime(fromIso)} to ${formatTime(untilIso)}`;
}

/** Seconds as a clock, "09:41". Never negative. */
export function formatClock(totalSeconds: number): string {
  const seconds = Math.max(0, Math.ceil(totalSeconds));
  return `${pad(Math.floor(seconds / 60))}:${pad(seconds % 60)}`;
}

/** Seconds from `now` until an ISO timestamp, never negative. */
export function secondsUntil(iso: string, now: number): number {
  return Math.max(0, (new Date(iso).getTime() - now) / 1000);
}
