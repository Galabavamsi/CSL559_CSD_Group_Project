import { Redirect } from 'expo-router';

import { useDeliveryLocation } from '@/state/deliveryLocation';
import { useSession } from '@/state/session';

/** The front door: sends each person to the start of their part of the app. */
export default function Index() {
  const role = useSession((state) => state.user?.role ?? null);
  const hasLocation = useDeliveryLocation((state) => state.location !== null);

  if (role === null) return <Redirect href="/welcome" />;
  if (role === 'farmer') return <Redirect href="/farmer" />;
  if (role === 'agent') return <Redirect href="/agent" />;
  return <Redirect href={hasLocation ? '/home' : '/location'} />;
}
