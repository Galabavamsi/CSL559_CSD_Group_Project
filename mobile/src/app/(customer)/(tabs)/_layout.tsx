import { Redirect, Tabs } from 'expo-router';

import { TabBar } from '@/components/TabBar';
import { useDeliveryLocation } from '@/state/deliveryLocation';

export default function CustomerTabs() {
  const hasLocation = useDeliveryLocation((state) => state.location !== null);

  // Everything a customer sees depends on which hub serves them, so the address comes first.
  if (!hasLocation) return <Redirect href="/location" />;

  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(props) => <TabBar {...props} />}>
      <Tabs.Screen name="home" options={{ title: 'Shop' }} />
      <Tabs.Screen name="orders" options={{ title: 'Orders' }} />
      <Tabs.Screen name="profile" options={{ title: 'Profile' }} />
    </Tabs>
  );
}
