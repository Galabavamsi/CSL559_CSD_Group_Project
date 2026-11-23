/**
 * In-memory stand-in for the API, used when EXPO_PUBLIC_API_URL is not set.
 *
 * It keeps the rules of the real backend that the screens depend on: a cart is held whole or not at all, a hold
 * runs out and gives its stock back, paying takes the stock for good, and an order moves through its states as
 * time passes. Everything is forgotten when the app reloads.
 */
import { MOCK_HOLD_SECONDS, MOCK_ORDER_STEP_SECONDS } from '@/config';
import { computeBill } from '@/lib/bill';
import { isoDateAfter } from '@/lib/dates';
import { distanceKm } from '@/lib/geo';
import { useSession } from '@/state/session';

import type { ApiClient } from '../client';
import { ApiError } from '../errors';
import type {
  CartLine,
  DeliveryAddress,
  Hold,
  HoldStatus,
  Hub,
  LatLng,
  Order,
  OrderEvent,
  OrderLine,
  OrderStatus,
  Product,
  Role,
  Serviceability,
  User,
} from '../types';
import {
  AGENT_NAMES,
  CATALOGUE,
  CITIES,
  CITY_PRICE_FACTOR,
  FARMS,
  HUBS,
  MARKDOWN_FACTOR,
  MOCK_OTP_CODE,
} from './data';
import { createFarmSupplyMock } from './farms';

const OTP_TTL_SECONDS = 600;
const OTP_RESEND_SECONDS = 60;
const OTP_MAX_ATTEMPTS = 5;
const OTP_MAX_PER_HOUR = 5;
const ACCESS_TOKEN_SECONDS = 3600;
const PAYMENT_SETTLE_MS = 3000;
const BUSY_RADIUS_FACTOR = 0.7;
const BUSY_PENALTY_MINUTES = 5;

const EMAIL = /^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$/;
const PHONE = /^\+?[0-9]{7,15}$/;

interface StockRow {
  onHand: number;
  reserved: number;
}

interface LoginCode {
  role: Role;
  sentAt: number;
  attempts: number;
  used: boolean;
  /** When each code of the last hour was asked for, newest last. */
  askedAt: number[];
}

interface StoredHold {
  id: string;
  orderId: string;
  hubId: number;
  ownerId: number;
  status: HoldStatus;
  expiresAt: number;
  lines: CartLine[];
}

interface StoredOrder {
  id: string;
  ownerId: number;
  hubId: number;
  hubName: string;
  placedAt: number;
  cancelledAt: number | null;
  lines: OrderLine[];
  itemTotal: number;
  savings: number;
  deliveryFee: number;
  total: number;
  address: DeliveryAddress;
  deliveryCode: string;
  pooledWith: number;
  etaMinutes: number | null;
  agentName: string;
}

function delay<T>(value: () => T): Promise<T> {
  // Long enough for loading states to be seen, short enough not to annoy.
  const ms = 250 + Math.random() * 300;
  return new Promise((resolve, reject) => {
    setTimeout(() => {
      try {
        resolve(value());
      } catch (error) {
        reject(error);
      }
    }, ms);
  });
}

function randomDigits(count: number): string {
  let digits = '';
  for (let i = 0; i < count; i += 1) digits += Math.floor(Math.random() * 10);
  return digits;
}

export function createMockClient(): ApiClient {
  const users = new Map<string, User>(); // by email
  const emailByToken = new Map<string, string>();
  const loginCodes = new Map<string, LoginCode>(); // by email
  const stock = new Map<string, StockRow>(); // by "hubId:productId"
  const holds = new Map<string, StoredHold>();
  const orders = new Map<string, StoredOrder>();
  let nextUserId = 1;

  for (const hub of HUBS) {
    for (const item of CATALOGUE) {
      const onHand = item.stock === 0 ? 0 : item.stock + ((hub.id + item.id) % 5);
      stock.set(`${hub.id}:${item.id}`, { onHand, reserved: 0 });
    }
  }

  // ------------------------------------------------------------------ helpers

  function currentUser(): User {
    const { accessToken, user: remembered } = useSession.getState();
    if (!accessToken) throw new ApiError(401, 'not_logged_in', 'Sign in to continue.');
    const email = emailByToken.get(accessToken);
    const known = email ? users.get(email) : undefined;
    if (known) return known;
    // The app reloaded: memory is empty but the device still has its session. Carry on as that user.
    if (remembered && accessToken.startsWith('mock.')) {
      const restored = { ...remembered };
      users.set(restored.email, restored);
      emailByToken.set(accessToken, restored.email);
      nextUserId = Math.max(nextUserId, restored.id + 1);
      return restored;
    }
    throw new ApiError(401, 'bad_token', 'This session has ended. Sign in again.');
  }

  function findHub(hubId: number): Hub {
    const hub = HUBS.find((candidate) => candidate.id === hubId);
    if (!hub) throw new ApiError(404, 'not_found', `Store ${hubId} does not exist`);
    return hub;
  }

  function stockRow(hubId: number, productId: number): StockRow | undefined {
    return stock.get(`${hubId}:${productId}`);
  }

  function availableUnits(hubId: number, productId: number): number {
    const row = stockRow(hubId, productId);
    return row ? Math.max(0, row.onHand - row.reserved) : 0;
  }

  /** Places this run's customer has asked for delivery at. */
  const serviceRequests = new Set<string>();

  /** Give back the stock of every hold whose time has run out. The real API does this on a timer. */
  function sweepExpiredHolds(): void {
    const now = Date.now();
    for (const hold of holds.values()) {
      if (hold.status === 'held' && hold.expiresAt <= now) giveBack(hold, 'expired');
    }
  }

  function giveBack(hold: StoredHold, status: 'released' | 'expired'): void {
    for (const line of hold.lines) {
      const row = stockRow(hold.hubId, line.productId);
      if (row) row.reserved -= line.quantity;
    }
    hold.status = status;
  }

  function productsOf(hub: Hub): Product[] {
    const city = hub.city ?? CITIES[0].slug;
    const priceFactor = CITY_PRICE_FACTOR[city] ?? 1;
    return CATALOGUE.map((item) => {
      const price = Math.round(item.basePrice * priceFactor);
      return {
        id: item.id,
        name: item.name,
        category: item.category,
        unitLabel: item.unitLabel,
        price,
        markdownPrice: item.useByInDays <= 1 ? Math.round(price * MARKDOWN_FACTOR) : null,
        markdownUnits: null, // the demo marks down every unit of an item in its last day
        grade: item.grade,
        harvestDate: isoDateAfter(-item.harvestedDaysAgo),
        useByDate: isoDateAfter(item.useByInDays),
        farmName: FARMS[city]?.[item.farm] ?? null,
        imageUrl: null,
        available: availableUnits(hub.id, item.id),
      };
    });
  }

  function holdView(hold: StoredHold): Hold {
    return {
      id: hold.id,
      orderId: hold.orderId,
      hubId: hold.hubId,
      status: hold.status,
      expiresAt: new Date(hold.expiresAt).toISOString(),
      lines: hold.lines.map((line) => ({ ...line })),
    };
  }

  function findHold(holdId: string): StoredHold {
    const hold = holds.get(holdId);
    if (!hold) throw new ApiError(404, 'not_found', `Reservation ${holdId} does not exist`);
    return hold;
  }

  /** An order's state is worked out from the clock: one step every MOCK_ORDER_STEP_SECONDS after payment. */
  function orderView(order: StoredOrder): Order {
    const step = MOCK_ORDER_STEP_SECONDS * 1000;
    const paidAt = order.placedAt + PAYMENT_SETTLE_MS;
    const schedule: [OrderStatus, number][] = [
      ['placed', order.placedAt],
      ['confirmed', paidAt],
      ['packed', paidAt + step],
      ['pooled', paidAt + 2 * step],
      ['out_for_delivery', paidAt + 3 * step],
      ['delivered', paidAt + 5 * step],
    ];
    const until = order.cancelledAt ?? Date.now();
    const history: OrderEvent[] = schedule
      .filter(([, at]) => at <= until)
      .map(([status, at]) => ({ status, at: new Date(at).toISOString() }));
    if (order.cancelledAt !== null) {
      history.push({ status: 'cancelled', at: new Date(order.cancelledAt).toISOString() });
    }
    const status = history[history.length - 1].status;
    const reached = (wanted: OrderStatus) => history.some((event) => event.status === wanted);

    return {
      id: order.id,
      status,
      placedAt: new Date(order.placedAt).toISOString(),
      history,
      hubId: order.hubId,
      hubName: order.hubName,
      lines: order.lines.map((line) => ({ ...line })),
      itemTotal: order.itemTotal,
      savings: order.savings,
      deliveryFee: order.deliveryFee,
      total: order.total,
      address: { ...order.address },
      deliveryCode: order.deliveryCode,
      pooledWith: reached('pooled') ? order.pooledWith : null,
      etaMinutes: order.etaMinutes,
      agentName: reached('pooled') ? order.agentName : null,
      canCancel: status === 'placed' || status === 'confirmed',
    };
  }

  function findOwnOrder(orderId: string): StoredOrder {
    const order = orders.get(orderId);
    if (!order || order.ownerId !== currentUser().id) {
      throw new ApiError(404, 'not_found', `Order ${orderId} does not exist`);
    }
    return order;
  }

  function serviceabilityOf(point: LatLng): Serviceability {
    const byDistance = HUBS.filter((hub) => hub.status !== 'closed')
      .map((hub) => ({ hub, km: distanceKm(point, hub) }))
      .sort((a, b) => a.km - b.km);
    const serving = byDistance.find(
      ({ hub, km }) => km <= hub.radiusKm * (hub.status === 'busy' ? BUSY_RADIUS_FACTOR : 1),
    );
    if (!serving) {
      const nearest = byDistance[0];
      return {
        serviceable: false,
        h3Cell: null,
        nearestHubName: nearest?.hub.name ?? null,
        nearestDistanceKm: nearest ? Math.round(nearest.km * 100) / 100 : null,
      };
    }
    const busyMinutes = serving.hub.status === 'busy' ? BUSY_PENALTY_MINUTES : 0;
    return {
      serviceable: true,
      hubId: serving.hub.id,
      hubName: serving.hub.name,
      hubStatus: serving.hub.status,
      distanceKm: Math.round(serving.km * 100) / 100,
      // Pooled delivery: time to pack and group the batch, then the ride.
      etaMinutes: Math.ceil(20 + serving.km * 4 + busyMinutes),
      h3Cell: null,
    };
  }

  // ------------------------------------------------------------------ the client

  return {
    mode: 'mock',

    requestOtp: (rawEmail, role) =>
      delay(() => {
        const email = rawEmail.trim().toLowerCase();
        if (!EMAIL.test(email)) throw new ApiError(422, 'bad_email', 'That does not look like an email address');
        const now = Date.now();
        const previous = loginCodes.get(email);
        const askedThisHour = (previous?.askedAt ?? []).filter((at) => now - at < 3_600_000);
        const waited = previous ? (now - previous.sentAt) / 1000 : Infinity;
        if (waited < OTP_RESEND_SECONDS) {
          const wait = Math.ceil(OTP_RESEND_SECONDS - waited);
          throw new ApiError(429, 'too_soon', `A code was sent a moment ago. You can ask again in ${wait} seconds.`, {
            retry_after_seconds: wait,
          });
        }
        if (askedThisHour.length >= OTP_MAX_PER_HOUR) {
          throw new ApiError(429, 'too_many_codes', 'Too many codes were asked for this address. Try again in an hour.', {
            retry_after_seconds: 3600,
          });
        }
        loginCodes.set(email, { role, sentAt: now, attempts: 0, used: false, askedAt: [...askedThisHour, now] });
        return { sent: true, expiresInSeconds: OTP_TTL_SECONDS, retryAfterSeconds: OTP_RESEND_SECONDS };
      }),

    verifyOtp: (rawEmail, code) =>
      delay(() => {
        const email = rawEmail.trim().toLowerCase();
        const badCode = new ApiError(401, 'bad_code', 'That code is not right, or it has expired. Ask for a new one.');
        const entry = loginCodes.get(email);
        if (!entry || entry.used || Date.now() - entry.sentAt > OTP_TTL_SECONDS * 1000) throw badCode;
        if (entry.attempts >= OTP_MAX_ATTEMPTS) {
          throw new ApiError(429, 'too_many_attempts', 'Too many wrong codes. Ask for a new one.');
        }
        entry.attempts += 1;
        if (code !== MOCK_OTP_CODE) throw badCode;
        entry.used = true; // a code works once

        let user = users.get(email);
        const isNew = user === undefined;
        if (!user) {
          user = { id: nextUserId, role: entry.role, name: null, email, phone: null, city: null };
          nextUserId += 1;
          users.set(email, user);
        }
        const accessToken = `mock.${user.id}.${randomDigits(12)}`;
        emailByToken.set(accessToken, email);
        return {
          accessToken,
          // The same shape as the real API. The mock's tokens never run out, so this one is never exchanged.
          refreshToken: `mock-refresh.${randomDigits(24)}`,
          expiresInSeconds: ACCESS_TOKEN_SECONDS,
          user: { ...user },
          isNew,
        };
      }),

    signOut: () =>
      delay(() => {
        const { accessToken } = useSession.getState();
        if (accessToken) emailByToken.delete(accessToken);
      }),

    getMe: () => delay(() => ({ ...currentUser() })),

    updateMe: (changes) =>
      delay(() => {
        const user = currentUser();
        if (changes.name !== undefined) user.name = changes.name?.trim() || null;
        if (changes.phone !== undefined) {
          const phone = (changes.phone ?? '').replace(/[\s-]/g, '');
          if (phone && !PHONE.test(phone)) {
            throw new ApiError(422, 'bad_phone', 'A phone number is 7 to 15 digits, with an optional + in front');
          }
          user.phone = phone || null;
        }
        if (changes.city !== undefined) {
          if (changes.city !== null && !CITIES.some((city) => city.slug === changes.city)) {
            throw new ApiError(422, 'unknown_city', `There is no city '${changes.city}'`);
          }
          user.city = changes.city;
        }
        return { ...user };
      }),

    listCities: () => delay(() => CITIES.map((city) => ({ ...city }))),

    listHubs: (citySlug) =>
      delay(() => HUBS.filter((hub) => citySlug === undefined || hub.city === citySlug).map((hub) => ({ ...hub }))),

    checkServiceability: (point) => delay(() => serviceabilityOf(point)),

    requestService: (point) =>
      delay(() => {
        currentUser();
        if (serviceabilityOf(point).serviceable) {
          throw new ApiError(409, 'already_served', 'A hub delivers to this address now');
        }
        const key = `${point.lat.toFixed(3)},${point.lng.toFixed(3)}`;
        const isNew = !serviceRequests.has(key);
        serviceRequests.add(key);
        return { isNew, othersNearby: 3 }; // the demo's neighbours
      }),

    listProducts: (hubId) =>
      delay(() => {
        sweepExpiredHolds();
        return productsOf(findHub(hubId));
      }),

    createHold: (request) =>
      delay(() => {
        const owner = currentUser();
        findHub(request.hubId);
        sweepExpiredHolds();

        const existing = [...holds.values()].find((hold) => hold.orderId === request.orderId);
        if (existing) return holdView(existing); // a retry of the same request

        if (request.lines.length === 0) {
          throw new ApiError(422, 'empty_cart', 'A reservation needs at least one line');
        }
        const short = request.lines.filter(
          (line) => line.quantity > availableUnits(request.hubId, line.productId),
        );
        if (short.length > 0) {
          throw new ApiError(409, 'insufficient_stock', 'Not enough stock for one or more items', {
            lines: short.map((line) => ({
              sku_id: line.productId,
              requested: line.quantity,
              available: availableUnits(request.hubId, line.productId),
            })),
          });
        }

        for (const line of request.lines) {
          const row = stockRow(request.hubId, line.productId);
          if (row) row.reserved += line.quantity;
        }
        const hold: StoredHold = {
          id: `hold-${randomDigits(10)}`,
          orderId: request.orderId,
          hubId: request.hubId,
          ownerId: owner.id,
          status: 'held',
          expiresAt: Date.now() + MOCK_HOLD_SECONDS * 1000,
          lines: request.lines.map((line) => ({ ...line })),
        };
        holds.set(hold.id, hold);
        return holdView(hold);
      }),

    getHold: (holdId) =>
      delay(() => {
        sweepExpiredHolds();
        return holdView(findHold(holdId));
      }),

    releaseHold: (holdId) =>
      delay(() => {
        sweepExpiredHolds();
        const hold = findHold(holdId);
        if (hold.status === 'held') giveBack(hold, 'released');
        else if (hold.status === 'confirmed' || hold.status === 'fulfilled') {
          throw new ApiError(409, 'already_paid', 'This order is already paid.');
        }
        return holdView(hold);
      }),

    getHoldBill: (holdId) =>
      delay(() => {
        sweepExpiredHolds();
        const hold = findHold(holdId);
        if (hold.status === 'expired') {
          throw new ApiError(409, 'hold_expired', 'The 10-minute hold ran out; the items are back on sale');
        }
        if (hold.status !== 'held') {
          throw new ApiError(409, 'not_held', `Reservation is ${hold.status}, so there is nothing to pay for`);
        }
        const { lines, itemTotal, savings, deliveryFee, total } = computeBill(hold.lines, productsOf(findHub(hold.hubId)));
        return { lines, itemTotal, savings, deliveryFee, total };
      }),

    placeOrder: (request) =>
      delay(() => {
        const owner = currentUser();
        sweepExpiredHolds();
        const hold = findHold(request.holdId);
        const paidBefore = orders.get(hold.orderId);
        if (paidBefore) return orderView(paidBefore); // a retry of a payment that went through
        if (hold.status === 'expired') {
          throw new ApiError(409, 'hold_expired', 'The 10-minute hold ran out; the items are back on sale');
        }
        if (hold.status !== 'held') {
          throw new ApiError(409, 'not_held', `Reservation is ${hold.status}, so it cannot be confirmed`);
        }

        const hub = findHub(hold.hubId);
        const bill = computeBill(hold.lines, productsOf(hub)); // the mock prices the order itself, like a server
        for (const line of hold.lines) {
          const row = stockRow(hold.hubId, line.productId);
          if (row) {
            row.onHand -= line.quantity;
            row.reserved -= line.quantity;
          }
        }
        hold.status = 'confirmed';

        const order: StoredOrder = {
          id: hold.orderId,
          ownerId: owner.id,
          hubId: hub.id,
          hubName: hub.name,
          placedAt: Date.now(),
          cancelledAt: null,
          lines: bill.lines,
          itemTotal: bill.itemTotal,
          savings: bill.savings,
          deliveryFee: bill.deliveryFee,
          total: bill.total,
          address: { ...request.address },
          deliveryCode: randomDigits(4),
          pooledWith: 2 + Math.floor(Math.random() * 4),
          etaMinutes: request.etaMinutes,
          agentName: AGENT_NAMES[Math.floor(Math.random() * AGENT_NAMES.length)],
        };
        orders.set(order.id, order);
        return orderView(order);
      }),

    listOrders: () =>
      delay(() => {
        const owner = currentUser();
        return [...orders.values()]
          .filter((order) => order.ownerId === owner.id)
          .sort((a, b) => b.placedAt - a.placedAt)
          .map(orderView);
      }),

    getOrder: (orderId) => delay(() => orderView(findOwnOrder(orderId))),

    cancelOrder: (orderId) =>
      delay(() => {
        const order = findOwnOrder(orderId);
        const view = orderView(order);
        if (view.status === 'cancelled') return view;
        if (!view.canCancel) {
          throw new ApiError(409, 'too_late', 'This order is already packed, so it can no longer be cancelled.');
        }
        order.cancelledAt = Date.now();
        for (const line of order.lines) {
          const row = stockRow(order.hubId, line.productId);
          if (row) row.onHand += line.quantity;
        }
        return orderView(order);
      }),

    ...createFarmSupplyMock(currentUser, delay),
  };
}
