/**
 * The real API over HTTP. Each method maps one backend answer (snake_case JSON) to the app's own types.
 *
 * Used as the backend has them today: accounts (email codes, sessions, profile), cities, hubs, serviceability,
 * availability per hub, reservations (hold, confirm, release) and farm supply (produce items, farms, listings).
 * Customer orders do not exist on the backend yet: see `deviceOrders.ts` for how they are bridged.
 */
import { useSession } from '@/state/session';

import type { ApiClient } from './client';
import { readDeviceOrders, saveDeviceOrder, type DeviceOrder } from './deviceOrders';
import { ApiError } from './errors';
import type {
  AuthSession,
  City,
  Farm,
  Grade,
  Hold,
  HoldStatus,
  Hub,
  Listing,
  ListingStatus,
  Order,
  OrderStatus,
  ProduceItem,
  Product,
  QualityGrade,
  Role,
  Serviceability,
  User,
} from './types';

const TIMEOUT_MS = 15_000;
/** An access token this close to running out is renewed before the request is sent. */
const RENEW_BEFORE_MS = 60_000;

// ---------------------------------------------------------------------- what the API sends

interface RawUser {
  id: number;
  role: Role;
  name: string | null;
  email: string;
  phone: string | null;
  city: string | null;
}

interface RawSession {
  access_token: string;
  refresh_token?: string | null;
  expires_in?: number | null;
  user: RawUser;
  is_new?: boolean;
}

interface RawCity {
  city: string;
  name: string;
  tier: number;
  lat: number;
  lng: number;
  radius_km: number;
  hub_radius_km: number;
  hubs: number;
}

interface RawStore {
  store_id: number;
  name: string;
  lat: number;
  lng: number;
  radius_km: number;
  status: string;
  city: string | null;
}

interface RawServiceability {
  serviceable: boolean;
  store_id: number | null;
  h3_cell?: string | null;
  store?: string;
  status?: string;
  distance_km?: number;
  eta_minutes?: number;
  nearest_store?: string | null;
  nearest_distance_km?: number | null;
}

/**
 * GET /v1/stores/{id}/availability. Today it sends the first five fields; a produce unit's label and family come
 * from /v1/produce-items. The batch fields (grade, dates, markdown, farm, photo) are read as soon as the API
 * starts sending them and are simply absent from the screens until then.
 */
interface RawAvailability {
  sku_id: number;
  name: string;
  category: string;
  price: number;
  atp: number;
  unit_label?: string | null;
  markdown_price?: number | null;
  grade?: string | null;
  harvest_date?: string | null;
  use_by_date?: string | null;
  farm_name?: string | null;
  image_url?: string | null;
}

interface RawReservation {
  reservation_id: string;
  order_id: string;
  store_id: number;
  status: HoldStatus;
  expires_at: string;
  lines: { sku_id: number; qty: number }[];
}

interface RawProduceItem {
  item_id: number;
  name: string;
  family: string;
  shelf_life_days: number;
  units: { sku_id: number; name: string; unit_label: string | null; unit_grams: number | null; price: number }[];
}

interface RawFarm {
  farm_id: number;
  name: string;
  lat: number;
  lng: number;
  area_acres: number | null;
  nearest_hub: { store_id: number; name: string; distance_km: number } | null;
  delivered_kg_30d: number;
  rejected_kg_30d: number;
  rejection_rate_30d: number | null;
}

interface RawListing {
  listing_id: number;
  farm_id: number;
  farm: string;
  item_id: number;
  item: string;
  qty_kg: number;
  price_per_kg: number;
  harvest_date: string;
  status: ListingStatus;
  store_id: number;
  hub: string;
  drop_from: string;
  drop_until: string;
  quality_check: {
    grade: QualityGrade;
    received_kg: number;
    accepted_kg: number;
    rejected_kg: number;
    trim_kg: number;
    remarks: string | null;
    checked_at: string;
  } | null;
}

// ---------------------------------------------------------------------- mapping

function toUser(raw: RawUser): User {
  return { id: raw.id, role: raw.role, name: raw.name, email: raw.email, phone: raw.phone, city: raw.city };
}

function toSession(raw: RawSession): AuthSession {
  return {
    accessToken: raw.access_token,
    refreshToken: raw.refresh_token ?? null,
    expiresInSeconds: raw.expires_in ?? null,
    user: toUser(raw.user),
    isNew: raw.is_new ?? false,
  };
}

function toCity(raw: RawCity): City {
  return {
    slug: raw.city,
    name: raw.name,
    tier: raw.tier,
    lat: raw.lat,
    lng: raw.lng,
    radiusKm: raw.radius_km,
    hubRadiusKm: raw.hub_radius_km,
    hubs: raw.hubs,
  };
}

function toHub(raw: RawStore): Hub {
  return {
    id: raw.store_id,
    name: raw.name,
    lat: raw.lat,
    lng: raw.lng,
    radiusKm: raw.radius_km,
    status: raw.status,
    city: raw.city,
  };
}

function toServiceability(raw: RawServiceability): Serviceability {
  if (raw.serviceable && raw.store_id !== null) {
    return {
      serviceable: true,
      hubId: raw.store_id,
      hubName: raw.store ?? `Hub ${raw.store_id}`,
      hubStatus: raw.status ?? 'open',
      distanceKm: raw.distance_km ?? 0,
      etaMinutes: raw.eta_minutes ?? 0,
      h3Cell: raw.h3_cell ?? null,
    };
  }
  return {
    serviceable: false,
    h3Cell: raw.h3_cell ?? null,
    nearestHubName: raw.nearest_store ?? null,
    nearestDistanceKm: raw.nearest_distance_km ?? null,
  };
}

function toGrade(raw: string | null | undefined): Grade | null {
  return raw === 'A' || raw === 'B' ? raw : null;
}

function slug(text: string): string {
  return text.trim().toLowerCase().replace(/[\s_]+/g, '-');
}

/** What /v1/produce-items knows about one sellable unit. */
interface UnitInfo {
  itemName: string;
  family: string;
  unitLabel: string | null;
}

/** The backend's produce families, as the app's category slugs. */
const CATEGORY_OF_FAMILY: Record<string, string> = { leafy: 'leafy-greens' };

function toProduct(raw: RawAvailability, unit: UnitInfo | undefined): Product {
  return {
    id: raw.sku_id,
    // A produce unit is stored as "Tomato, 500 g" under the category "Tomato"; the shop shows the item's own
    // name, its unit label and its family instead.
    name: unit ? unit.itemName : raw.name,
    category: unit ? (CATEGORY_OF_FAMILY[unit.family] ?? slug(unit.family)) : slug(raw.category),
    unitLabel: raw.unit_label ?? unit?.unitLabel ?? null,
    price: raw.price,
    markdownPrice: raw.markdown_price ?? null,
    grade: toGrade(raw.grade),
    harvestDate: raw.harvest_date ?? null,
    useByDate: raw.use_by_date ?? null,
    farmName: raw.farm_name ?? null,
    imageUrl: raw.image_url ?? null,
    available: Math.max(0, raw.atp),
  };
}

function toHold(raw: RawReservation): Hold {
  return {
    id: raw.reservation_id,
    orderId: raw.order_id,
    hubId: raw.store_id,
    status: raw.status,
    expiresAt: raw.expires_at,
    lines: raw.lines.map((line) => ({ productId: line.sku_id, quantity: line.qty })),
  };
}

function toProduceItem(raw: RawProduceItem): ProduceItem {
  return {
    id: raw.item_id,
    name: raw.name,
    family: raw.family,
    shelfLifeDays: raw.shelf_life_days,
    units: raw.units.map((unit) => ({
      skuId: unit.sku_id,
      name: unit.name,
      unitLabel: unit.unit_label,
      unitGrams: unit.unit_grams,
      price: unit.price,
    })),
  };
}

function toFarm(raw: RawFarm): Farm {
  return {
    id: raw.farm_id,
    name: raw.name,
    lat: raw.lat,
    lng: raw.lng,
    areaAcres: raw.area_acres,
    nearestHub: raw.nearest_hub && {
      hubId: raw.nearest_hub.store_id,
      name: raw.nearest_hub.name,
      distanceKm: raw.nearest_hub.distance_km,
    },
    deliveredKg30d: raw.delivered_kg_30d,
    rejectedKg30d: raw.rejected_kg_30d,
    rejectionRate30d: raw.rejection_rate_30d,
  };
}

function toListing(raw: RawListing): Listing {
  return {
    id: raw.listing_id,
    farmId: raw.farm_id,
    farmName: raw.farm,
    itemId: raw.item_id,
    itemName: raw.item,
    qtyKg: raw.qty_kg,
    pricePerKg: raw.price_per_kg,
    harvestDate: raw.harvest_date,
    status: raw.status,
    hubId: raw.store_id,
    hubName: raw.hub,
    dropFrom: raw.drop_from,
    dropUntil: raw.drop_until,
    qualityCheck: raw.quality_check && {
      grade: raw.quality_check.grade,
      receivedKg: raw.quality_check.received_kg,
      acceptedKg: raw.quality_check.accepted_kg,
      rejectedKg: raw.quality_check.rejected_kg,
      trimKg: raw.quality_check.trim_kg,
      remarks: raw.quality_check.remarks,
      checkedAt: raw.quality_check.checked_at,
    },
  };
}

/** How far a reservation's status says the order has come. Later stages are not visible to the app yet. */
const ORDER_STATUS_OF: Record<HoldStatus, OrderStatus> = {
  held: 'placed',
  confirmed: 'confirmed',
  fulfilled: 'packed',
  released: 'cancelled',
  expired: 'cancelled',
  cancelled: 'cancelled',
};

function toApiError(status: number, payload: unknown): ApiError {
  if (typeof payload === 'object' && payload !== null) {
    const { error, detail } = payload as { error?: unknown; detail?: unknown };
    if (typeof error === 'object' && error !== null) {
      const { code, message, details } = error as { code?: unknown; message?: unknown; details?: unknown };
      if (typeof code === 'string' && typeof message === 'string') {
        const extra = typeof details === 'object' && details !== null ? (details as Record<string, unknown>) : {};
        return new ApiError(status, code, message, extra);
      }
    }
    if (Array.isArray(detail)) {
      // The framework's own answer to a request that fails validation, before any business rule runs.
      return new ApiError(status, 'validation_error', 'Please check what you entered and try again.', {
        fields: detail,
      });
    }
  }
  if (status === 404) {
    return new ApiError(status, 'http_404', 'The server does not offer this yet. Please try again later.');
  }
  if (status >= 500) {
    return new ApiError(status, `http_${status}`, 'The server ran into a problem. Please try again in a moment.');
  }
  return new ApiError(status, `http_${status}`, 'The request could not be completed. Please try again.');
}

function sessionEnded(): ApiError {
  return new ApiError(401, 'session_ended', 'This session has ended. Sign in again.');
}

// ---------------------------------------------------------------------- the client

interface RequestOptions {
  body?: unknown;
  headers?: Record<string, string>;
  /** Sign-in calls: sent without a token and never retried through a session renewal. */
  anonymous?: boolean;
}

export function createHttpClient(baseUrl: string): ApiClient {
  /** The one renewal in flight, shared by every caller that needs it. */
  let renewal: Promise<boolean> | null = null;
  let unitInfo: Promise<Map<number, UnitInfo>> | null = null;

  async function send(method: string, path: string, options: RequestOptions, token: string | null): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      return await fetch(`${baseUrl}${path}`, {
        method,
        headers: {
          Accept: 'application/json',
          ...(options.body !== undefined && { 'Content-Type': 'application/json' }),
          ...(token && { Authorization: `Bearer ${token}` }),
          ...options.headers,
        },
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch {
      throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.');
    } finally {
      clearTimeout(timer);
    }
  }

  async function read<T>(response: Response): Promise<T> {
    const text = await response.text();
    let payload: unknown = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      // not JSON (a proxy's error page, for example): handled by status below
    }
    if (!response.ok) throw toApiError(response.status, payload);
    return payload as T;
  }

  /**
   * Exchange the refresh token for a new pair. A refresh token works once, and the server ends every session of
   * a user whose spent token turns up again, so two exchanges must never run side by side: every caller that
   * arrives while one is in flight waits for that same one. Resolves false when the session is over; rejects
   * when the server could not be reached (being offline is not being signed out).
   */
  function renewSession(): Promise<boolean> {
    renewal ??= (async () => {
      const { refreshToken, renew } = useSession.getState();
      if (!refreshToken) return false;
      try {
        const raw = await read<RawSession>(
          await send('POST', '/v1/auth/refresh', { body: { refresh_token: refreshToken } }, null),
        );
        renew(toSession(raw));
        return true;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return false;
        throw error;
      } finally {
        renewal = null;
      }
    })();
    return renewal;
  }

  async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    if (options.anonymous) return read<T>(await send(method, path, options, null));

    const endSession = (): never => {
      useSession.getState().signOut();
      throw sessionEnded();
    };

    // Renew a token that is about to run out before using it, rather than after it has been refused.
    const { accessTokenExpiresAt, refreshToken } = useSession.getState();
    const runningOut = accessTokenExpiresAt !== null && accessTokenExpiresAt - Date.now() < RENEW_BEFORE_MS;
    if ((runningOut && refreshToken) || renewal) {
      if (!(await renewSession())) endSession();
    }

    const tokenUsed = useSession.getState().accessToken;
    const response = await send(method, path, options, tokenUsed);
    if (response.status !== 401 || !tokenUsed) return read<T>(response);

    // Refused. If another call renewed the session while this one was on its way, the newer token is tried;
    // otherwise renew once. A second refusal means the session is over.
    if (useSession.getState().accessToken === tokenUsed && !(await renewSession())) endSession();
    const retry = await send(method, path, options, useSession.getState().accessToken);
    if (retry.status === 401) endSession();
    return read<T>(retry);
  }

  function signedInUser(): User {
    const { user } = useSession.getState();
    if (!user) throw new ApiError(401, 'not_logged_in', 'Sign in to continue.');
    return user;
  }

  /** Label and family of every produce unit, by SKU id. Asked for once; an API without it gives an empty map. */
  function produceUnitInfo(): Promise<Map<number, UnitInfo>> {
    unitInfo ??= request<RawProduceItem[]>('GET', '/v1/produce-items', { anonymous: true })
      .then((items) => {
        const bySku = new Map<number, UnitInfo>();
        for (const item of items) {
          for (const unit of item.units) {
            bySku.set(unit.sku_id, { itemName: item.name, family: item.family, unitLabel: unit.unit_label });
          }
        }
        return bySku;
      })
      .catch(() => {
        unitInfo = null; // try again with the next product list
        return new Map<number, UnitInfo>();
      });
    return unitInfo;
  }

  /** Bring a saved order up to date with its reservation, and save it again if it moved. */
  async function refreshed(userId: number, entry: DeviceOrder): Promise<Order> {
    const reservation = await request<RawReservation>('GET', `/v1/reservations/${entry.reservationId}`);
    const status = ORDER_STATUS_OF[reservation.status];
    if (status === entry.order.status) return entry.order;
    const order: Order = {
      ...entry.order,
      status,
      history: [...entry.order.history, { status, at: new Date().toISOString() }],
    };
    await saveDeviceOrder(userId, { ...entry, order });
    return order;
  }

  const isOpen = (order: Order) => order.status === 'placed' || order.status === 'confirmed';

  return {
    mode: 'http',

    requestOtp: async (email, role) => {
      const raw = await request<{ sent: boolean; expires_in_seconds: number; retry_after_seconds: number }>(
        'POST',
        '/v1/auth/otp/request',
        { body: { email, role }, anonymous: true },
      );
      return { sent: raw.sent, expiresInSeconds: raw.expires_in_seconds, retryAfterSeconds: raw.retry_after_seconds };
    },

    verifyOtp: async (email, code) =>
      toSession(await request<RawSession>('POST', '/v1/auth/otp/verify', { body: { email, code }, anonymous: true })),

    signOut: async () => {
      const { refreshToken } = useSession.getState();
      if (!refreshToken) return;
      await request('POST', '/v1/auth/logout', { body: { refresh_token: refreshToken }, anonymous: true });
    },

    getMe: async () => toUser(await request<RawUser>('GET', '/v1/me')),

    updateMe: async (changes) => toUser(await request<RawUser>('PATCH', '/v1/me', { body: changes })),

    listCities: async () => (await request<RawCity[]>('GET', '/v1/cities')).map(toCity),

    listHubs: async (citySlug) => {
      const query = citySlug ? `?city=${encodeURIComponent(citySlug)}` : '';
      return (await request<RawStore[]>('GET', `/v1/stores${query}`)).map(toHub);
    },

    checkServiceability: async ({ lat, lng }) =>
      toServiceability(await request<RawServiceability>('GET', `/v1/serviceability?lat=${lat}&lng=${lng}`)),

    listProducts: async (hubId) => {
      const [rows, units] = await Promise.all([
        request<RawAvailability[]>('GET', `/v1/stores/${hubId}/availability`),
        produceUnitInfo(),
      ]);
      return rows.map((row) => toProduct(row, units.get(row.sku_id)));
    },

    createHold: async ({ orderId, hubId, lines, h3Cell }) =>
      toHold(
        await request<RawReservation>('POST', '/v1/reservations', {
          body: {
            order_id: orderId,
            store_id: hubId,
            lines: lines.map((line) => ({ sku_id: line.productId, qty: line.quantity })),
            ...(h3Cell && { h3_cell: h3Cell }),
          },
        }),
      ),

    getHold: async (holdId) => toHold(await request<RawReservation>('GET', `/v1/reservations/${holdId}`)),

    releaseHold: async (holdId) => toHold(await request<RawReservation>('DELETE', `/v1/reservations/${holdId}`)),

    placeOrder: async (placed) => {
      const user = signedInUser();
      // Confirming the reservation is how an order is paid for today.
      const reservation = await request<RawReservation>('POST', `/v1/reservations/${placed.holdId}/confirm`);
      const now = new Date().toISOString();
      const order: Order = {
        id: reservation.order_id,
        status: 'confirmed',
        placedAt: now,
        history: [
          { status: 'placed', at: now },
          { status: 'confirmed', at: now },
        ],
        hubId: reservation.store_id,
        hubName: placed.hubName,
        lines: placed.lines,
        itemTotal: placed.itemTotal,
        savings: placed.savings,
        deliveryFee: placed.deliveryFee,
        total: placed.total,
        address: placed.address,
        deliveryCode: null,
        pooledWith: null,
        etaMinutes: placed.etaMinutes,
        agentName: null,
        canCancel: false,
      };
      await saveDeviceOrder(user.id, { reservationId: reservation.reservation_id, order });
      return order;
    },

    listOrders: async () => {
      const user = signedInUser();
      const saved = await readDeviceOrders(user.id);
      // Only orders that can still move are asked about; if the API cannot be reached, the saved copy is shown.
      return Promise.all(
        saved.map((entry) => (isOpen(entry.order) ? refreshed(user.id, entry).catch(() => entry.order) : entry.order)),
      );
    },

    getOrder: async (orderId) => {
      const user = signedInUser();
      const entry = (await readDeviceOrders(user.id)).find((saved) => saved.order.id === orderId);
      if (!entry) throw new ApiError(404, 'not_found', `Order ${orderId} does not exist`);
      return isOpen(entry.order) ? refreshed(user.id, entry) : entry.order;
    },

    cancelOrder: async () => {
      throw new ApiError(501, 'not_supported', 'Orders cannot be cancelled from the app yet. Please contact the hub.');
    },

    listProduceItems: async () => (await request<RawProduceItem[]>('GET', '/v1/produce-items')).map(toProduceItem),

    listFarms: async () => (await request<RawFarm[]>('GET', '/v1/farms')).map(toFarm),

    createFarm: async ({ name, lat, lng, accuracyM }) =>
      toFarm(
        await request<RawFarm>('POST', '/v1/farms', {
          body: { name, lat, lng, ...(accuracyM !== null && { accuracy_m: accuracyM }) },
        }),
      ),

    listListings: async () => (await request<RawListing[]>('GET', '/v1/listings')).map(toListing),

    createListing: async ({ farmId, itemId, qtyKg, pricePerKg, harvestDate }, idempotencyKey) =>
      toListing(
        await request<RawListing>('POST', '/v1/listings', {
          body: {
            farm_id: farmId,
            item_id: itemId,
            qty_kg: qtyKg,
            price_per_kg: pricePerKg,
            harvest_date: harvestDate,
          },
          headers: { 'Idempotency-Key': idempotencyKey },
        }),
      ),

    cancelListing: async (listingId) =>
      toListing(await request<RawListing>('POST', `/v1/listings/${listingId}/cancel`)),
  };
}
