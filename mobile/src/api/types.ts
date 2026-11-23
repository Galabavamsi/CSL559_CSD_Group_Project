/** The app's own data shapes. Both API clients (HTTP and mock) return these; screens never see raw JSON. */

export type Role = 'customer' | 'farmer' | 'agent';

export interface User {
  id: number;
  role: Role;
  name: string | null;
  email: string;
  phone: string | null;
  /** A city's slug, for example "bhilai". */
  city: string | null;
}

export interface OtpRequestResult {
  sent: boolean;
  expiresInSeconds: number;
  retryAfterSeconds: number;
}

export interface AuthSession {
  accessToken: string;
  /** Exchanged for a new pair before the access token runs out. Works once. */
  refreshToken: string | null;
  /** Seconds the access token lasts from now; null when the API does not say. */
  expiresInSeconds: number | null;
  user: User;
  isNew: boolean;
}

export interface ProfileChanges {
  name?: string | null;
  phone?: string | null;
  city?: string | null;
}

export interface LatLng {
  lat: number;
  lng: number;
}

export interface City {
  slug: string;
  name: string;
  tier: number;
  lat: number;
  lng: number;
  radiusKm: number;
  hubRadiusKm: number;
  hubs: number;
}

export interface Hub {
  id: number;
  name: string;
  lat: number;
  lng: number;
  radiusKm: number;
  /** "open", "busy" or "closed". */
  status: string;
  city: string | null;
}

export type Serviceability =
  | {
      serviceable: true;
      hubId: number;
      hubName: string;
      hubStatus: string;
      distanceKm: number;
      etaMinutes: number;
      /** Sent back with the hold so the network planner knows where demand is. */
      h3Cell: string | null;
    }
  | {
      serviceable: false;
      h3Cell: string | null;
      nearestHubName: string | null;
      nearestDistanceKm: number | null;
    };

export type Grade = 'A' | 'B';

/**
 * One sellable unit at one hub: a pack, a piece with a weight range, or a bunch. Never sold by weight.
 * Fields the API does not send yet are null and the screens leave that detail out.
 */
export interface Product {
  id: number;
  name: string;
  /** Category slug, for example "vegetables" or "leafy-greens". */
  category: string;
  /** "500 g pack", "1 piece · 400–600 g", "1 bunch". */
  unitLabel: string | null;
  /** Rupees for one unit. */
  price: number;
  /** Lower price for a batch with one day left; null when the batch is not marked down. */
  markdownPrice: number | null;
  /**
   * How many units the lower price applies to: an order for more pays the usual price for the rest.
   * Null when there is no markdown, or no limit on it.
   */
  markdownUnits: number | null;
  grade: Grade | null;
  /** Calendar dates as YYYY-MM-DD. */
  harvestDate: string | null;
  useByDate: string | null;
  farmName: string | null;
  imageUrl: string | null;
  /** Units a customer can buy right now. */
  available: number;
}

export interface CartLine {
  productId: number;
  quantity: number;
}

export type HoldStatus = 'held' | 'confirmed' | 'fulfilled' | 'released' | 'expired' | 'cancelled';

/** Stock set aside for a cart while the customer pays. */
export interface Hold {
  id: string;
  orderId: string;
  hubId: number;
  status: HoldStatus;
  /** ISO timestamp. */
  expiresAt: string;
  lines: CartLine[];
}

export interface HoldRequest {
  /** Also the idempotency key: asking twice with the same id returns the first hold. */
  orderId: string;
  hubId: number;
  lines: CartLine[];
  h3Cell: string | null;
}

export type OrderStatus =
  | 'placed'
  | 'confirmed'
  | 'packed'
  | 'pooled'
  | 'out_for_delivery'
  | 'delivered'
  | 'cancelled'
  | 'delivery_failed';

/**
 * Units of one product at one price. An order holds a product twice when some of its units came from a batch in
 * its last day and the rest did not.
 */
export interface OrderLine {
  productId: number;
  name: string;
  unitLabel: string | null;
  quantity: number;
  /** Rupees actually charged for one unit (the markdown price when there was one). */
  unitPrice: number;
  /** Rupees one unit costs without a markdown. */
  listPrice: number;
}

/** What a cart costs: its lines, and the sums the bill shows. */
export interface Bill {
  lines: OrderLine[];
  /** What the items cost after markdowns. */
  itemTotal: number;
  /** What markdowns took off the full price. */
  savings: number;
  deliveryFee: number;
  total: number;
}

export interface OrderEvent {
  status: OrderStatus;
  /** ISO timestamp. */
  at: string;
}

export interface DeliveryAddress {
  /** Area name, for example "Nehru Nagar, Bhilai". */
  label: string;
  /** House or flat and street, typed by the customer. */
  line: string;
  landmark: string | null;
  lat: number;
  lng: number;
}

export interface Order {
  id: string;
  status: OrderStatus;
  placedAt: string;
  /** Every state the order has reached so far, oldest first. */
  history: OrderEvent[];
  hubId: number;
  hubName: string;
  lines: OrderLine[];
  itemTotal: number;
  /** What rescue deals took off the full price. */
  savings: number;
  deliveryFee: number;
  total: number;
  address: DeliveryAddress;
  /** Four digits the customer reads to the delivery agent; null until the API issues one. */
  deliveryCode: string | null;
  /** How many neighbours' orders travel in the same batch; null until pooled. */
  pooledWith: number | null;
  etaMinutes: number | null;
  agentName: string | null;
  canCancel: boolean;
}

// ---------------------------------------------------------------------- farm supply

/** One unit customers buy an item in, for example Tomato as a "500 g" pack. */
export interface ProduceUnit {
  skuId: number;
  name: string;
  unitLabel: string | null;
  unitGrams: number | null;
  /** Rupees for one unit. */
  price: number;
}

/** A kind of produce a farmer can list. Farmers deal in kilograms of it; customers buy its units. */
export interface ProduceItem {
  id: number;
  name: string;
  /** "vegetables", "leafy", "fruits" or "herbs". */
  family: string;
  shelfLifeDays: number;
  units: ProduceUnit[];
}

export interface Farm {
  id: number;
  name: string;
  lat: number;
  lng: number;
  areaAcres: number | null;
  /** Null when no hub is within reach of the farm. */
  nearestHub: { hubId: number; name: string; distanceKm: number } | null;
  deliveredKg30d: number;
  rejectedKg30d: number;
  /** Rejected kg / delivered kg over 30 days; null until the farm has delivered anything. */
  rejectionRate30d: number | null;
}

export interface NewFarm {
  name: string;
  lat: number;
  lng: number;
  /** How sure the phone is of the location, in metres; null for a point not taken from GPS. */
  accuracyM: number | null;
}

export type QualityGrade = 'A' | 'B' | 'C' | 'reject';

/** What the hub found when it weighed and graded a lot. */
export interface QualityCheck {
  grade: QualityGrade;
  receivedKg: number;
  acceptedKg: number;
  rejectedKg: number;
  /** Accepted weight that did not fill a whole unit. */
  trimKg: number;
  remarks: string | null;
  checkedAt: string;
}

/** "listed" (on its way to the hub), "received" (weighed and graded) or "cancelled". */
export type ListingStatus = 'listed' | 'received' | 'cancelled';

export interface Listing {
  id: number;
  farmId: number;
  farmName: string;
  itemId: number;
  itemName: string;
  qtyKg: number;
  pricePerKg: number;
  /** Calendar date, YYYY-MM-DD. */
  harvestDate: string;
  status: ListingStatus;
  hubId: number;
  hubName: string;
  /** The window in which the hub takes the lot in, as ISO timestamps. */
  dropFrom: string;
  dropUntil: string;
  qualityCheck: QualityCheck | null;
}

export interface NewListing {
  farmId: number;
  itemId: number;
  qtyKg: number;
  pricePerKg: number;
  harvestDate: string;
}

/**
 * Paying for a hold. The bill is the one the customer was shown: the API works out its own, and refuses to
 * charge more than `total` (`price_changed`).
 */
export interface PlaceOrderRequest {
  holdId: string;
  hubName: string;
  lines: OrderLine[];
  itemTotal: number;
  savings: number;
  deliveryFee: number;
  total: number;
  address: DeliveryAddress;
  etaMinutes: number | null;
}
