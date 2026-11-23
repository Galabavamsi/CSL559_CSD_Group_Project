import { useMutation } from '@tanstack/react-query';

import { api } from '@/api';
import { emptyCart } from '@/features/cart/useCartActions';
import { useSession } from '@/state/session';

/**
 * Sign out. The server is told so the refresh token stops working, but the device signs out whether or not
 * that message gets through. The root layout clears cached data and shows the sign-in screen.
 */
export function useSignOut() {
  return useMutation({
    mutationFn: async () => {
      emptyCart();
      await api.signOut().catch(() => undefined);
    },
    onSettled: () => useSession.getState().signOut(),
  });
}
