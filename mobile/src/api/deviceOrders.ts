/**
 * Orders remembered on the device, for the HTTP client only.
 *
 * The API can hold a cart and take payment for it (reservations) but has no customer orders yet, so there is
 * nothing to list a customer's orders from. Until it has, the HTTP client writes each paid order here and reads
 * its progress from the reservation. When the API gains `/v1/orders`, this file goes away.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import type { Order } from './types';
import { storageName } from '@/config';

export interface DeviceOrder {
  reservationId: string;
  order: Order;
}

const storageKey = (userId: number) => storageName(`f2h.orders.${userId}`);

/** A user's orders, newest first. */
export async function readDeviceOrders(userId: number): Promise<DeviceOrder[]> {
  try {
    const stored = await AsyncStorage.getItem(storageKey(userId));
    const parsed: unknown = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed) ? (parsed as DeviceOrder[]) : [];
  } catch {
    return []; // unreadable storage: show no history
  }
}

/** Add an order, or replace the saved copy of the same order. */
export async function saveDeviceOrder(userId: number, entry: DeviceOrder): Promise<void> {
  const others = (await readDeviceOrders(userId)).filter((saved) => saved.order.id !== entry.order.id);
  const all = [entry, ...others].sort((a, b) => b.order.placedAt.localeCompare(a.order.placedAt));
  await AsyncStorage.setItem(storageKey(userId), JSON.stringify(all));
}
