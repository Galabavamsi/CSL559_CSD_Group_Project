import { useQueryClient } from '@tanstack/react-query';

import { api } from '@/api';
import { useProducts } from '@/api/queries';
import { computeBill, type Bill } from '@/lib/bill';
import { cartLines, cartUnitCount, useCart } from '@/state/cart';
import { useDeliveryLocation } from '@/state/deliveryLocation';

/**
 * Returns the function every stepper calls. Changing the cart while a hold is running releases that hold:
 * the hold was for the old quantities, and holding stock the customer no longer wants is unfair to others.
 */
export function useSetCartQuantity(): (productId: number, quantity: number) => void {
  const hubId = useDeliveryLocation((state) => state.location?.hubId ?? null);
  const queryClient = useQueryClient();

  return (productId, quantity) => {
    if (hubId === null) return;
    const { hold, setHold, setQuantity } = useCart.getState();
    if (hold) {
      setHold(null);
      api
        .releaseHold(hold.id)
        .catch(() => undefined) // it runs out by itself if this call is lost
        .finally(() => queryClient.invalidateQueries({ queryKey: ['products'] }));
    }
    setQuantity(hubId, productId, quantity);
  };
}

/** Empty the cart and give back any stock it was holding. For a change of hub and for signing out. */
export function emptyCart(): void {
  const { hold, clear } = useCart.getState();
  if (hold) api.releaseHold(hold.id).catch(() => undefined);
  clear();
}

export interface CartSummary {
  /** Total units in the cart. */
  count: number;
  /** Priced against the hub's current list; null until that list has loaded. */
  bill: Bill | null;
}

/** The cart of the current hub, priced. A cart left over from another hub counts as empty. */
export function useCartSummary(): CartSummary {
  const hubId = useDeliveryLocation((state) => state.location?.hubId ?? null);
  const cartHubId = useCart((state) => state.hubId);
  const quantities = useCart((state) => state.quantities);
  const { data: products } = useProducts(hubId);

  if (hubId === null || cartHubId !== hubId) return { count: 0, bill: null };
  return {
    count: cartUnitCount(quantities),
    bill: products ? computeBill(cartLines(quantities), products) : null,
  };
}
