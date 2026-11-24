/**
 * Mock delivery: an agent chooses a hub and goes on duty, and a few seconds later a trip appears with two or
 * three stops made up from the areas around that hub. Every screen of a delivery run can then be walked through
 * with no hub packing real orders. The rules and error codes are the backend's (app/modules/delivery/service.py).
 */
import { presetAreasOf } from '@/features/location/presetAreas';
import { distanceKm } from '@/lib/geo';
import { newOrderId } from '@/lib/ids';

import type { ApiClient } from '../client';
import { ApiError } from '../errors';
import type { AgentState, Hub, Trip, TripStop, User } from '../types';
import { CITIES, HUBS, MOCK_DOOR_CODE, TRIP_CUSTOMERS } from './data';

/** The backend's DOOR_CODE_TRIES and ROAD_FACTOR (app/config.py). */
const DOOR_CODE_TRIES = 5;
const ROAD_FACTOR = 1.7;
/**
 * How long packed bags wait before an agent on duty is given their trip. The app asks for the agent's state every
 * five seconds, so the trip shows on the phone about six seconds after going on duty.
 */
const TRIP_AFTER_MS = 4000;
/** After a trip ends, how long the hub is quiet before the next bags are packed. */
const QUIET_MS = 10_000;

type Delivery = Pick<
  ApiClient,
  'getAgent' | 'chooseAgentHub' | 'setAgentDuty' | 'loadBag' | 'deliverOrder' | 'failDelivery'
>;

interface StoredAgent {
  hubId: number | null;
  onDuty: boolean;
  /** When the next trip is given to this agent; null while off duty or on a trip. */
  tripDueAt: number | null;
  trip: Trip | null;
  tripsMade: number;
}

/** Trips alternate between three stops and two. */
function tripSize(tripNo: number): number {
  return 2 + (tripNo % 2);
}

/** A trip to the areas nearest the hub, nearest first, which is close enough to the shortest round for a demo. */
function makeTrip(hub: Hub, tripNo: number): Trip {
  const city = CITIES.find((candidate) => candidate.slug === hub.city) ?? CITIES[0];
  const areas = presetAreasOf(city)
    .map((area) => ({ area, km: distanceKm(hub, area) }))
    .sort((a, b) => a.km - b.km)
    .slice(0, tripSize(tripNo))
    .map(({ area }) => area);
  const round = [hub, ...areas, hub];
  const straightKm = round.slice(1).reduce((sum, point, index) => sum + distanceKm(round[index], point), 0);

  return {
    id: tripNo,
    status: 'assigned',
    km: Math.round(straightKm * ROAD_FACTOR * 10) / 10,
    createdAt: new Date().toISOString(),
    leftAt: null,
    doneAt: null,
    hub: { id: hub.id, name: hub.name, lat: hub.lat, lng: hub.lng },
    stops: areas.map((area, index) => {
      const customer = TRIP_CUSTOMERS[(tripNo - 1 + index) % TRIP_CUSTOMERS.length];
      return {
        orderId: newOrderId(),
        seq: index + 1,
        status: 'waiting',
        crateSlot: `S-${String(((tripNo - 1) * 3 + index) % 24 + 1).padStart(2, '0')}`,
        units: 2 + ((tripNo + index) % 4),
        address: {
          label: `${area.name}, ${city.name}`,
          line: customer.line,
          landmark: customer.landmark,
          lat: area.lat,
          lng: area.lng,
        },
        customer: { name: customer.name, phone: customer.phone },
        failedReason: null,
        triesLeft: DOOR_CODE_TRIES,
      };
    }),
  };
}

/** A copy to hand out: the stored trip changes in place, and the app must never hold the object that changes. */
function copyOf(trip: Trip): Trip {
  return {
    ...trip,
    hub: { ...trip.hub },
    stops: trip.stops.map((stop) => ({ ...stop, address: { ...stop.address }, customer: { ...stop.customer } })),
  };
}

export function createDeliveryMock(
  currentUser: () => User,
  delay: <T>(work: () => T) => Promise<T>,
): Delivery {
  const agents = new Map<number, StoredAgent>(); // by user id

  function signedInAgent(): { user: User; agent: StoredAgent } {
    const user = currentUser();
    if (user.role !== 'agent') throw new ApiError(403, 'forbidden', `A ${user.role} may not do this`);
    let agent = agents.get(user.id);
    if (!agent) {
      agent = { hubId: null, onDuty: false, tripDueAt: null, trip: null, tripsMade: 0 };
      agents.set(user.id, agent);
    }
    return { user, agent };
  }

  function stateOf(user: User, agent: StoredAgent): AgentState {
    const hub = HUBS.find((candidate) => candidate.id === agent.hubId) ?? null;
    const now = Date.now();
    // The real API forms trips when an order is packed and on a timer; the mock forms one when it is next asked.
    if (hub && agent.onDuty && agent.trip === null && agent.tripDueAt !== null && agent.tripDueAt <= now) {
      agent.tripsMade += 1;
      agent.trip = makeTrip(hub, agent.tripsMade);
      agent.tripDueAt = null;
    }
    // Bags for the next trip are at the hub, except on a trip and in the quiet spell after one.
    const quiet = agent.tripDueAt !== null && agent.tripDueAt - now > TRIP_AFTER_MS;
    return {
      userId: user.id,
      name: user.name,
      hub: hub && { id: hub.id, name: hub.name, lat: hub.lat, lng: hub.lng },
      onDuty: agent.onDuty,
      trip: agent.trip && copyOf(agent.trip),
      waitingAtHub: hub && agent.trip === null && !quiet ? tripSize(agent.tripsMade + 1) : 0,
    };
  }

  function openTrip(agent: StoredAgent): Trip {
    if (!agent.trip) throw new ApiError(409, 'no_trip', 'You have no trip at the moment');
    return agent.trip;
  }

  function stopOf(trip: Trip, orderId: string): TripStop {
    const stop = trip.stops.find((candidate) => candidate.orderId === orderId);
    if (!stop) throw new ApiError(404, 'not_found', `Order on your trip ${orderId} does not exist`);
    return stop;
  }

  /** The stop of an order that is on the road, for a hand-over or a report that there was none. */
  function stopOnTheRoad(agent: StoredAgent, orderId: string): { trip: Trip; stop: TripStop } {
    const trip = openTrip(agent);
    const stop = stopOf(trip, orderId);
    if (trip.status !== 'out') {
      throw new ApiError(409, 'not_left', 'Check every bag out of the hub before making a delivery');
    }
    return { trip, stop };
  }

  /** A stop is over. After the last one the trip is done and the agent is free for the next. */
  function endStop(agent: StoredAgent, trip: Trip, stop: TripStop, status: 'delivered' | 'failed'): Trip {
    stop.status = status;
    if (trip.stops.every((other) => other.status === 'delivered' || other.status === 'failed')) {
      trip.status = 'done';
      trip.doneAt = new Date().toISOString();
      agent.trip = null;
      if (agent.onDuty) agent.tripDueAt = Date.now() + QUIET_MS + TRIP_AFTER_MS;
    }
    return copyOf(trip);
  }

  return {
    getAgent: () =>
      delay(() => {
        const { user, agent } = signedInAgent();
        return stateOf(user, agent);
      }),

    chooseAgentHub: (hubId) =>
      delay(() => {
        const { user, agent } = signedInAgent();
        const hub = HUBS.find((candidate) => candidate.id === hubId);
        if (!hub || hub.status === 'closed') throw new ApiError(404, 'not_found', `Hub ${hubId} does not exist`);
        if (agent.onDuty || agent.trip) throw new ApiError(409, 'on_duty', 'Go off duty before changing your hub');
        agent.hubId = hubId;
        return stateOf(user, agent);
      }),

    setAgentDuty: (onDuty) =>
      delay(() => {
        const { user, agent } = signedInAgent();
        if (onDuty) {
          if (agent.hubId === null) throw new ApiError(409, 'no_hub', 'Choose the hub you work from first');
          if (!agent.onDuty) {
            agent.onDuty = true;
            agent.tripDueAt = agent.trip ? null : Date.now() + TRIP_AFTER_MS;
          }
        } else {
          if (agent.trip) throw new ApiError(409, 'on_a_trip', 'Finish your trip before going off duty');
          agent.onDuty = false;
          agent.tripDueAt = null;
        }
        return stateOf(user, agent);
      }),

    loadBag: (orderId) =>
      delay(() => {
        const { agent } = signedInAgent();
        const trip = openTrip(agent);
        const stop = stopOf(trip, orderId);
        if (stop.status === 'waiting') stop.status = 'loaded';
        if (trip.status === 'assigned' && trip.stops.every((other) => other.status !== 'waiting')) {
          trip.status = 'out';
          trip.leftAt = new Date().toISOString();
        }
        return copyOf(trip);
      }),

    deliverOrder: (orderId, code) =>
      delay(() => {
        const { agent } = signedInAgent();
        const { trip, stop } = stopOnTheRoad(agent, orderId);
        if (stop.status === 'delivered') return copyOf(trip); // a retry of a hand-over that went through
        if (stop.status !== 'loaded') {
          throw new ApiError(409, 'stop_over', `Order ${orderId} is already marked ${stop.status}`);
        }
        if (stop.triesLeft <= 0) {
          throw new ApiError(
            409,
            'code_locked',
            'Too many wrong codes. Report this stop as not delivered; the hub will call the customer.',
          );
        }
        if (code !== MOCK_DOOR_CODE) {
          stop.triesLeft -= 1;
          throw new ApiError(
            422,
            'wrong_code',
            stop.triesLeft > 0
              ? "That is not this order's code. Ask the customer to read it again."
              : "That is not this order's code, and there are no tries left.",
            { tries_left: stop.triesLeft },
          );
        }
        return endStop(agent, trip, stop, 'delivered');
      }),

    failDelivery: (orderId, reason) =>
      delay(() => {
        const { agent } = signedInAgent();
        const { trip, stop } = stopOnTheRoad(agent, orderId);
        if (stop.status === 'failed') return copyOf(trip); // a retry of a report that went through
        if (stop.status !== 'loaded') {
          throw new ApiError(409, 'stop_over', `Order ${orderId} is already marked ${stop.status}`);
        }
        stop.failedReason = reason;
        return endStop(agent, trip, stop, 'failed');
      }),
  };
}
