import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

/** Where the customer wants deliveries, and the hub that serves that point. */
export interface DeliveryLocation {
  /** Area name shown in headers, for example "Nehru Nagar, Bhilai". */
  label: string;
  lat: number;
  lng: number;
  hubId: number;
  hubName: string;
  etaMinutes: number;
  h3Cell: string | null;
}

interface DeliveryLocationState {
  location: DeliveryLocation | null;
  /** House or flat and street. Asked for at checkout, kept for the next order. */
  addressLine: string;
  landmark: string;
  setLocation: (location: DeliveryLocation) => void;
  setAddress: (addressLine: string, landmark: string) => void;
}

export const useDeliveryLocation = create<DeliveryLocationState>()(
  persist(
    (set) => ({
      location: null,
      addressLine: '',
      landmark: '',
      setLocation: (location) =>
        set((state) =>
          // A new point is a new address: the old house number would be wrong there.
          state.location && state.location.lat === location.lat && state.location.lng === location.lng
            ? { location }
            : { location, addressLine: '', landmark: '' },
        ),
      setAddress: (addressLine, landmark) => set({ addressLine, landmark }),
    }),
    {
      name: 'f2h.delivery-location',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: ({ location, addressLine, landmark }) => ({ location, addressLine, landmark }),
    },
  ),
);
