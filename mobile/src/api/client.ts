import type {
  AgentState,
  AuthSession,
  Bill,
  City,
  DeliveryFailReason,
  Farm,
  Hold,
  HoldRequest,
  Hub,
  LatLng,
  Listing,
  NewFarm,
  NewListing,
  Order,
  OtpRequestResult,
  PlaceOrderRequest,
  ProduceItem,
  Product,
  ProfileChanges,
  Role,
  Serviceability,
  ServiceRequestResult,
  Trip,
  User,
} from './types';

/**
 * Everything the app asks of a backend. Two implementations exist: `createHttpClient` (the real API) and
 * `createMockClient` (in-memory demo data). Every method rejects with an `ApiError`.
 */
export interface ApiClient {
  readonly mode: 'http' | 'mock';

  // Accounts
  requestOtp(email: string, role: Role): Promise<OtpRequestResult>;
  verifyOtp(email: string, code: string): Promise<AuthSession>;
  signOut(): Promise<void>;
  getMe(): Promise<User>;
  updateMe(changes: ProfileChanges): Promise<User>;

  // Where we deliver
  listCities(): Promise<City[]>;
  listHubs(citySlug?: string): Promise<Hub[]>;
  checkServiceability(point: LatLng): Promise<Serviceability>;
  /** Ask for delivery at a place no hub serves. `label` is the area's name. Safe to repeat. */
  requestService(point: LatLng, label: string | null): Promise<ServiceRequestResult>;

  // What a hub can deliver right now
  listProducts(hubId: number): Promise<Product[]>;

  // Checkout: hold the cart, then pay inside the hold
  createHold(request: HoldRequest): Promise<Hold>;
  getHold(holdId: string): Promise<Hold>;
  releaseHold(holdId: string): Promise<Hold>;
  /** What paying for the hold costs right now, as the hub would charge it. */
  getHoldBill(holdId: string): Promise<Bill>;
  /** Takes the (demo) payment and turns the hold into an order. */
  placeOrder(request: PlaceOrderRequest): Promise<Order>;

  // Orders
  listOrders(): Promise<Order[]>;
  getOrder(orderId: string): Promise<Order>;
  cancelOrder(orderId: string): Promise<Order>;

  // Farm supply (farmers only)
  listProduceItems(): Promise<ProduceItem[]>;
  listFarms(): Promise<Farm[]>;
  createFarm(farm: NewFarm): Promise<Farm>;
  listListings(): Promise<Listing[]>;
  /** `idempotencyKey`: any unique string per form; a retry with the same key lists the lot once. */
  createListing(listing: NewListing, idempotencyKey: string): Promise<Listing>;
  cancelListing(listingId: number): Promise<Listing>;

  // Delivery (agents only)
  getAgent(): Promise<AgentState>;
  /** Only while off duty (`on_duty`). */
  chooseAgentHub(hubId: number): Promise<AgentState>;
  /** Going on duty needs a hub (`no_hub`); going off duty is refused during a trip (`on_a_trip`). */
  setAgentDuty(onDuty: boolean): Promise<AgentState>;
  /** Confirm one bag at the hub. The trip is "out" once every bag is confirmed. Safe to repeat. */
  loadBag(orderId: string): Promise<Trip>;
  /** Hand an order over against the four digits the customer reads out (`wrong_code`, `code_locked`). */
  deliverOrder(orderId: string, code: string): Promise<Trip>;
  failDelivery(orderId: string, reason: DeliveryFailReason): Promise<Trip>;
}
