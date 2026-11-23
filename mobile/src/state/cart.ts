import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import type { CartLine, Hold } from '@/api/types';

/** The hold the customer is paying for, remembered so checkout survives leaving the screen or a restart. */
export interface ActiveHold {
  id: string;
  orderId: string;
  hubId: number;
  /** When this device was told about the hold; the start of the countdown bar. */
  heldAt: string;
  expiresAt: string;
}

interface CartState {
  /** Stock is per hub, so a cart belongs to one hub. */
  hubId: number | null;
  /** Units per product id. A product that is not in the cart has no entry. */
  quantities: Record<number, number>;
  hold: ActiveHold | null;
  setQuantity: (hubId: number, productId: number, quantity: number) => void;
  setHold: (hold: Hold | null) => void;
  clear: () => void;
}

export const useCart = create<CartState>()(
  persist(
    (set) => ({
      hubId: null,
      quantities: {},
      hold: null,
      setQuantity: (hubId, productId, quantity) =>
        set((state) => {
          const quantities = state.hubId === hubId ? { ...state.quantities } : {};
          if (quantity > 0) quantities[productId] = quantity;
          else delete quantities[productId];
          return { hubId, quantities };
        }),
      setHold: (hold) =>
        set({
          hold: hold && {
            id: hold.id,
            orderId: hold.orderId,
            hubId: hold.hubId,
            heldAt: new Date().toISOString(),
            expiresAt: hold.expiresAt,
          },
        }),
      clear: () => set({ hubId: null, quantities: {}, hold: null }),
    }),
    {
      name: 'f2h.cart',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: ({ hubId, quantities, hold }) => ({ hubId, quantities, hold }),
    },
  ),
);

export function cartLines(quantities: Record<number, number>): CartLine[] {
  return Object.entries(quantities).map(([productId, quantity]) => ({ productId: Number(productId), quantity }));
}

export function cartUnitCount(quantities: Record<number, number>): number {
  return Object.values(quantities).reduce((sum, quantity) => sum + quantity, 0);
}
