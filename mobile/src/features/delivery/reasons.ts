import type { DeliveryFailReason } from '@/api';

/** Why an order could not be handed over, in the agent's words and in the order the choices are offered. */
export const FAIL_REASONS: { value: DeliveryFailReason; label: string }[] = [
  { value: 'nobody_home', label: 'Nobody was home' },
  { value: 'refused', label: 'The customer refused it' },
  { value: 'not_found', label: 'Could not find the address' },
];

/** The words for a reason, or null when the API gave none (or one this version does not know). */
export function failReasonLabel(reason: DeliveryFailReason | null): string | null {
  return FAIL_REASONS.find((candidate) => candidate.value === reason)?.label ?? null;
}
