import type { OrderStatus } from '@/api';
import type { IconName } from '@/features/catalogue/categories';

/** The states a delivered order passes through, in order. Cancelled and failed orders leave this path. */
export const ORDER_STEPS: OrderStatus[] = ['placed', 'confirmed', 'packed', 'pooled', 'out_for_delivery', 'delivered'];

interface StatusInfo {
  label: string;
  /** What is happening now, in one sentence. */
  description: string;
  icon: IconName;
}

export const STATUS_INFO: Record<OrderStatus, StatusInfo> = {
  placed: {
    label: 'Placed',
    description: 'We have your order and are confirming the payment.',
    icon: 'receipt-text-outline',
  },
  confirmed: {
    label: 'Confirmed',
    description: 'Payment received. The hub is about to pack your items.',
    icon: 'check-decagram',
  },
  packed: {
    label: 'Packed',
    description: 'Your items are packed and sealed at the hub.',
    icon: 'package-variant-closed',
  },
  pooled: {
    label: 'Pooled',
    description: "Grouped with your neighbours' orders into one delivery run.",
    icon: 'account-group-outline',
  },
  out_for_delivery: {
    label: 'Out for delivery',
    description: 'The delivery agent is on the way. Keep your delivery code ready.',
    icon: 'moped-outline',
  },
  delivered: {
    label: 'Delivered',
    description: 'Your order was handed over. Enjoy your produce.',
    icon: 'home-variant-outline',
  },
  cancelled: {
    label: 'Cancelled',
    description: 'This order was cancelled and its items went back on sale.',
    icon: 'close-circle-outline',
  },
  delivery_failed: {
    label: 'Delivery failed',
    description: 'The delivery agent could not hand over your order. Please contact your hub to arrange a new delivery.',
    icon: 'alert-circle-outline',
  },
};

/** How a status is coloured wherever it is shown. */
export type StatusTone = 'active' | 'done' | 'problem';

export function statusTone(status: OrderStatus): StatusTone {
  if (status === 'cancelled' || status === 'delivery_failed') return 'problem';
  return status === 'delivered' ? 'done' : 'active';
}
