/** TanStack Query hooks: the only way screens read from or write to the API. */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { useCart } from '@/state/cart';
import { useSession } from '@/state/session';

import { api } from './index';
import type {
  AgentState,
  DeliveryFailReason,
  HoldRequest,
  LatLng,
  NewFarm,
  NewListing,
  Order,
  OrderStatus,
  PlaceOrderRequest,
  ProfileChanges,
  Role,
  Trip,
} from './types';

export const queryKeys = {
  me: ['me'] as const,
  cities: ['cities'] as const,
  hubs: (citySlug: string | null) => ['hubs', citySlug] as const,
  serviceability: (point: LatLng | null) => ['serviceability', point?.lat, point?.lng] as const,
  products: (hubId: number | null) => ['products', hubId] as const,
  hold: (holdId: string | null) => ['hold', holdId] as const,
  holdBill: (holdId: string | null) => ['hold', holdId, 'bill'] as const,
  orders: ['orders'] as const,
  order: (orderId: string) => ['orders', orderId] as const,
  produceItems: ['produce-items'] as const,
  farms: ['farms'] as const,
  listings: ['listings'] as const,
  agent: ['agent'] as const,
};

const FINAL_STATES: OrderStatus[] = ['delivered', 'cancelled', 'delivery_failed'];

export function isFinalStatus(status: OrderStatus): boolean {
  return FINAL_STATES.includes(status);
}

// ---------------------------------------------------------------------- accounts

export function useRequestOtp() {
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: Role }) => api.requestOtp(email, role),
  });
}

export function useVerifyOtp() {
  return useMutation({
    mutationFn: ({ email, code }: { email: string; code: string }) => api.verifyOtp(email, code),
    onSuccess: (session) => useSession.getState().signIn(session),
  });
}

/** Keeps the remembered user in step with the server while someone is signed in. */
export function useMe() {
  const signedIn = useSession((state) => state.accessToken !== null);
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async () => {
      const user = await api.getMe();
      useSession.getState().setUser(user);
      return user;
    },
    enabled: signedIn,
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (changes: ProfileChanges) => api.updateMe(changes),
    onSuccess: (user) => {
      useSession.getState().setUser(user);
      queryClient.setQueryData(queryKeys.me, user);
    },
  });
}

// ---------------------------------------------------------------------- where we deliver

export function useCities() {
  return useQuery({ queryKey: queryKeys.cities, queryFn: () => api.listCities(), staleTime: 10 * 60_000 });
}

/** The hubs of one city. Waits until a city is named. */
export function useHubs(citySlug: string | null) {
  return useQuery({
    queryKey: queryKeys.hubs(citySlug),
    queryFn: () => api.listHubs(citySlug as string),
    enabled: citySlug !== null,
    staleTime: 60_000,
  });
}

export function useServiceability(point: LatLng | null) {
  return useQuery({
    queryKey: queryKeys.serviceability(point),
    queryFn: () => api.checkServiceability(point as LatLng),
    enabled: point !== null,
    staleTime: 60_000,
  });
}

/** Ask for delivery at a place no hub serves. */
export function useRequestService() {
  return useMutation({
    mutationFn: ({ point, label }: { point: LatLng; label: string | null }) => api.requestService(point, label),
  });
}

// ---------------------------------------------------------------------- catalogue

export function useProducts(hubId: number | null) {
  return useQuery({
    queryKey: queryKeys.products(hubId),
    queryFn: () => api.listProducts(hubId as number),
    enabled: hubId !== null,
    staleTime: 20_000,
  });
}

// ---------------------------------------------------------------------- checkout

export function useCreateHold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: HoldRequest) => api.createHold(request),
    onSuccess: (hold) => {
      useCart.getState().setHold(hold);
      queryClient.setQueryData(queryKeys.hold(hold.id), hold);
    },
    // Held or refused, the hub's stock numbers are different now.
    onSettled: (_hold, _error, request) =>
      queryClient.invalidateQueries({ queryKey: queryKeys.products(request.hubId) }),
  });
}

export function useHold(holdId: string | null) {
  return useQuery({
    queryKey: queryKeys.hold(holdId),
    queryFn: () => api.getHold(holdId as string),
    enabled: holdId !== null,
    staleTime: 0,
    retry: false,
  });
}

/**
 * What the hub would charge for the held cart right now. Asked again every so often: another customer can pay
 * first for the last units at a lower price, and the total shown has to follow.
 */
export function useHoldBill(holdId: string | null) {
  return useQuery({
    queryKey: queryKeys.holdBill(holdId),
    queryFn: () => api.getHoldBill(holdId as string),
    enabled: holdId !== null,
    staleTime: 0,
    refetchInterval: 20_000,
    retry: false,
  });
}

export function useReleaseHold() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (holdId: string) => api.releaseHold(holdId),
    onSettled: () => {
      useCart.getState().setHold(null);
      return queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}

export function usePlaceOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: PlaceOrderRequest) => api.placeOrder(request),
    onSuccess: (order) => {
      useCart.getState().clear();
      queryClient.setQueryData(queryKeys.order(order.id), order);
      // Not awaited: the screen should move on to the order at once, not after these lists have reloaded.
      void queryClient.invalidateQueries({ queryKey: queryKeys.orders, exact: true });
      void queryClient.invalidateQueries({ queryKey: ['products'] });
    },
  });
}

// ---------------------------------------------------------------------- orders

export function useOrders() {
  return useQuery({
    queryKey: queryKeys.orders,
    queryFn: () => api.listOrders(),
    // While something is on its way, keep the list moving too.
    refetchInterval: (query) => (query.state.data?.some((order) => !isFinalStatus(order.status)) ? 5000 : false),
  });
}

export function useOrder(orderId: string) {
  return useQuery({
    queryKey: queryKeys.order(orderId),
    queryFn: () => api.getOrder(orderId),
    refetchInterval: (query) => (query.state.data && isFinalStatus(query.state.data.status) ? false : 3000),
  });
}

// ---------------------------------------------------------------------- farm supply

export function useProduceItems() {
  return useQuery({ queryKey: queryKeys.produceItems, queryFn: () => api.listProduceItems(), staleTime: 10 * 60_000 });
}

export function useFarms() {
  return useQuery({ queryKey: queryKeys.farms, queryFn: () => api.listFarms() });
}

export function useCreateFarm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (farm: NewFarm) => api.createFarm(farm),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.farms }),
  });
}

export function useListings() {
  return useQuery({
    queryKey: queryKeys.listings,
    queryFn: () => api.listListings(),
    // A listed lot is waiting for the hub's quality check: look again now and then while one is.
    refetchInterval: (query) => (query.state.data?.some((listing) => listing.status === 'listed') ? 15_000 : false),
  });
}

export function useCreateListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ listing, idempotencyKey }: { listing: NewListing; idempotencyKey: string }) =>
      api.createListing(listing, idempotencyKey),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.listings }),
  });
}

export function useCancelListing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (listingId: number) => api.cancelListing(listingId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.listings }),
  });
}

export function useCancelOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => api.cancelOrder(orderId),
    onSuccess: (order: Order) => {
      queryClient.setQueryData(queryKeys.order(order.id), order);
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.orders, exact: true }),
        queryClient.invalidateQueries({ queryKey: ['products'] }),
      ]);
    },
  });
}

// ---------------------------------------------------------------------- delivery

/**
 * The agent's hub, duty and trip. Asked again every few seconds while they are on duty or on a trip: that is how
 * a new trip reaches the phone.
 */
export function useAgent() {
  return useQuery({
    queryKey: queryKeys.agent,
    queryFn: () => api.getAgent(),
    staleTime: 0,
    refetchInterval: (query) => (query.state.data?.onDuty || query.state.data?.trip ? 5000 : false),
  });
}

/**
 * Put what the API just answered into the agent's cached state. An answer to a question asked before the change
 * may still be on its way and would put the old state back, so it is dropped first.
 */
async function writeAgent(
  queryClient: QueryClient,
  change: (agent: AgentState | undefined) => AgentState | undefined,
): Promise<void> {
  await queryClient.cancelQueries({ queryKey: queryKeys.agent });
  queryClient.setQueryData<AgentState>(queryKeys.agent, change);
}

export function useChooseAgentHub() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (hubId: number) => api.chooseAgentHub(hubId),
    onSuccess: (agent) => writeAgent(queryClient, () => agent),
    // A refusal means the phone was behind (on duty after all, say): ask for the state as the server has it.
    // Not awaited, here and below: the message should show at once, not after that answer.
    onError: () => void queryClient.invalidateQueries({ queryKey: queryKeys.agent }),
  });
}

export function useSetAgentDuty() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (onDuty: boolean) => api.setAgentDuty(onDuty),
    onSuccess: (agent) => writeAgent(queryClient, () => agent),
    onError: () => void queryClient.invalidateQueries({ queryKey: queryKeys.agent }),
  });
}

/**
 * One step of a trip. The API answers with the trip as it stands now, which replaces the cached one. After the
 * last stop that trip is "done": it stays cached for the moment it takes to ask what comes next, which is no trip
 * or the next one. A refusal means the phone was behind (or a wrong code used up a try), so the state is asked
 * for again.
 */
function useTripStep<Step>(mutationFn: (step: Step) => Promise<Trip>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async (trip) => {
      await writeAgent(queryClient, (agent) => agent && { ...agent, trip });
      if (trip.status === 'done') void queryClient.invalidateQueries({ queryKey: queryKeys.agent });
    },
    onError: () => void queryClient.invalidateQueries({ queryKey: queryKeys.agent }),
  });
}

/** Confirm one bag at the hub, by its order id. */
export function useLoadBag() {
  return useTripStep((orderId: string) => api.loadBag(orderId));
}

/** Hand an order over against the code the customer reads out. */
export function useDeliverOrder() {
  return useTripStep(({ orderId, code }: { orderId: string; code: string }) => api.deliverOrder(orderId, code));
}

/** Report that an order could not be handed over. */
export function useFailDelivery() {
  return useTripStep(({ orderId, reason }: { orderId: string; reason: DeliveryFailReason }) =>
    api.failDelivery(orderId, reason),
  );
}
