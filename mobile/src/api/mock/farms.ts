/**
 * Mock farm supply: a farmer registers farms and lists lots; a hub and a drop slot are chosen as the backend
 * chooses them, and after a while the hub's quality check appears on the listing, so "My listings" can be seen
 * in each of its states without a hub worker.
 */
import { MOCK_ORDER_STEP_SECONDS } from '@/config';
import { daysFromToday, isoDateAfter } from '@/lib/dates';
import { distanceKm } from '@/lib/geo';

import type { ApiClient } from '../client';
import { ApiError } from '../errors';
import type { Farm, LatLng, Listing, ProduceItem, QualityCheck, User } from '../types';
import { CATALOGUE, CITY_PRICE_FACTOR, HUBS } from './data';

/** The backend's rules (app/config.py), repeated here so the mock refuses what the API would refuse. */
const FARM_LOCATION_MAX_ACCURACY_M = 50;
const HUB_SEARCH_KM = 60;
const LISTING_MAX_KG = 2000;
const LISTING_MAX_DAYS_AHEAD = 7;
const MIN_REMAINING_SHELF_LIFE = 0.5;
const INTAKE_START_HOUR = 6;
const INTAKE_HOURS = 3;
/** How many order steps pass before the mock hub "receives" a listed lot. */
const RECEIVED_AFTER_STEPS = 4;

const FAMILY_OF_CATEGORY: Record<string, string> = { 'leafy-greens': 'leafy' };

type FarmSupply = Pick<
  ApiClient,
  'listProduceItems' | 'listFarms' | 'createFarm' | 'listListings' | 'createListing' | 'cancelListing'
>;

interface StoredFarm {
  id: number;
  farmerId: number;
  name: string;
  lat: number;
  lng: number;
}

interface StoredListing {
  id: number;
  farmerId: number;
  farm: StoredFarm;
  item: ProduceItem;
  qtyKg: number;
  pricePerKg: number;
  harvestDate: string;
  hubId: number;
  hubName: string;
  dropFrom: number;
  dropUntil: number;
  createdAt: number;
  cancelled: boolean;
}

function nearestOpenHub(point: LatLng) {
  const [nearest] = HUBS.filter((hub) => hub.status !== 'closed')
    .map((hub) => ({ hub, km: distanceKm(point, hub) }))
    .sort((a, b) => a.km - b.km);
  return nearest && nearest.km <= HUB_SEARCH_KM ? nearest : null;
}

const PRODUCE_ITEMS: ProduceItem[] = CATALOGUE.map((item) => ({
  id: item.id,
  name: item.name,
  family: FAMILY_OF_CATEGORY[item.category] ?? item.category,
  shelfLifeDays: item.harvestedDaysAgo + item.useByInDays,
  units: [
    {
      skuId: item.id,
      name: `${item.name}, ${item.unitLabel}`,
      unitLabel: item.unitLabel,
      unitGrams: null,
      price: Math.round(item.basePrice * CITY_PRICE_FACTOR.bhilai),
    },
  ],
})).sort((a, b) => a.name.localeCompare(b.name));

export function createFarmSupplyMock(
  currentUser: () => User,
  delay: <T>(work: () => T) => Promise<T>,
): FarmSupply {
  const farms: StoredFarm[] = [];
  const listings: StoredListing[] = [];
  const listingIdByKey = new Map<string, number>();
  let nextFarmId = 1;
  let nextListingId = 1;

  function farmer(): User {
    const user = currentUser();
    if (user.role !== 'farmer') throw new ApiError(403, 'forbidden', `A ${user.role} may not do this`);
    return user;
  }

  function isReceived(listing: StoredListing): boolean {
    return (
      !listing.cancelled &&
      Date.now() - listing.createdAt >= RECEIVED_AFTER_STEPS * MOCK_ORDER_STEP_SECONDS * 1000
    );
  }

  /** The mock hub accepts most of a lot and turns a little away; an odd-numbered lot is graded B. */
  function qualityCheckOf(listing: StoredListing): QualityCheck {
    const rejectedKg = Math.round(listing.qtyKg * 0.04 * 10) / 10;
    const acceptedKg = Math.round((listing.qtyKg - rejectedKg) * 10) / 10;
    return {
      grade: listing.id % 2 === 0 ? 'A' : 'B',
      receivedKg: listing.qtyKg,
      acceptedKg,
      rejectedKg,
      trimKg: 0,
      remarks: rejectedKg > 0 ? 'A few bruised pieces were set aside.' : null,
      checkedAt: new Date(listing.createdAt + RECEIVED_AFTER_STEPS * MOCK_ORDER_STEP_SECONDS * 1000).toISOString(),
    };
  }

  function listingView(listing: StoredListing): Listing {
    const received = isReceived(listing);
    return {
      id: listing.id,
      farmId: listing.farm.id,
      farmName: listing.farm.name,
      itemId: listing.item.id,
      itemName: listing.item.name,
      qtyKg: listing.qtyKg,
      pricePerKg: listing.pricePerKg,
      harvestDate: listing.harvestDate,
      status: listing.cancelled ? 'cancelled' : received ? 'received' : 'listed',
      hubId: listing.hubId,
      hubName: listing.hubName,
      dropFrom: new Date(listing.dropFrom).toISOString(),
      dropUntil: new Date(listing.dropUntil).toISOString(),
      qualityCheck: received ? qualityCheckOf(listing) : null,
    };
  }

  function farmView(farm: StoredFarm): Farm {
    const nearest = nearestOpenHub(farm);
    const checks = listings
      .filter((listing) => listing.farm.id === farm.id && isReceived(listing))
      .map(qualityCheckOf);
    const delivered = checks.reduce((sum, check) => sum + check.receivedKg, 0);
    const rejected = checks.reduce((sum, check) => sum + check.rejectedKg, 0);
    return {
      id: farm.id,
      name: farm.name,
      lat: farm.lat,
      lng: farm.lng,
      areaAcres: null,
      nearestHub: nearest && {
        hubId: nearest.hub.id,
        name: nearest.hub.name,
        distanceKm: Math.round(nearest.km * 10) / 10,
      },
      deliveredKg30d: delivered,
      rejectedKg30d: rejected,
      rejectionRate30d: delivered > 0 ? Math.round((rejected / delivered) * 1000) / 1000 : null,
    };
  }

  /** The next morning intake window that has not started yet and is not before the harvest date. */
  function nextDropSlot(harvestDate: string): { from: number; until: number } {
    const now = new Date();
    const firstDay = now.getHours() < INTAKE_START_HOUR ? 0 : 1;
    const daysAhead = Math.max(firstDay, daysFromToday(harvestDate, now));
    const from = new Date(now.getFullYear(), now.getMonth(), now.getDate() + daysAhead, INTAKE_START_HOUR).getTime();
    return { from, until: from + INTAKE_HOURS * 3_600_000 };
  }

  return {
    listProduceItems: () => delay(() => PRODUCE_ITEMS.map((item) => ({ ...item, units: [...item.units] }))),

    listFarms: () =>
      delay(() => {
        const owner = farmer();
        return farms.filter((farm) => farm.farmerId === owner.id).map(farmView);
      }),

    createFarm: (input) =>
      delay(() => {
        const owner = farmer();
        const name = input.name.trim();
        if (name === '') throw new ApiError(422, 'validation_error', 'Please check what you entered and try again.');
        if (input.accuracyM !== null && input.accuracyM > FARM_LOCATION_MAX_ACCURACY_M) {
          throw new ApiError(
            422,
            'location_too_rough',
            `The phone is sure of this location only to ${input.accuracyM.toFixed(0)} m. Wait for a better fix ` +
              `(under ${FARM_LOCATION_MAX_ACCURACY_M} m) or place the pin by hand.`,
            { accuracy_m: input.accuracyM, needed_m: FARM_LOCATION_MAX_ACCURACY_M },
          );
        }
        const farm: StoredFarm = { id: nextFarmId, farmerId: owner.id, name, lat: input.lat, lng: input.lng };
        nextFarmId += 1;
        farms.push(farm);
        return farmView(farm);
      }),

    listListings: () =>
      delay(() => {
        const owner = farmer();
        return listings
          .filter((listing) => listing.farmerId === owner.id)
          .sort((a, b) => b.id - a.id)
          .map(listingView);
      }),

    createListing: (input, idempotencyKey) =>
      delay(() => {
        const owner = farmer();
        const repeatOf = listings.find((listing) => listing.id === listingIdByKey.get(`${owner.id}:${idempotencyKey}`));
        if (repeatOf) return listingView(repeatOf); // a retry of the same form

        const farm = farms.find((candidate) => candidate.id === input.farmId && candidate.farmerId === owner.id);
        if (!farm) throw new ApiError(404, 'not_found', `Farm ${input.farmId} does not exist`);
        const item = PRODUCE_ITEMS.find((candidate) => candidate.id === input.itemId);
        if (!item) throw new ApiError(404, 'not_found', `Produce item ${input.itemId} does not exist`);
        if (!(input.qtyKg > 0 && input.qtyKg <= LISTING_MAX_KG && input.pricePerKg > 0)) {
          throw new ApiError(422, 'validation_error', 'Please check what you entered and try again.');
        }
        if (daysFromToday(input.harvestDate) > LISTING_MAX_DAYS_AHEAD) {
          throw new ApiError(422, 'too_far_ahead', `List produce at most ${LISTING_MAX_DAYS_AHEAD} days before its harvest`);
        }
        const slot = nextDropSlot(input.harvestDate);
        const dropDay = isoDateAfter(0, new Date(slot.from));
        const daysLeft = item.shelfLifeDays - (daysFromToday(dropDay) - daysFromToday(input.harvestDate));
        if (daysLeft < MIN_REMAINING_SHELF_LIFE * item.shelfLifeDays) {
          throw new ApiError(
            422,
            'too_old',
            `${item.name} keeps ${item.shelfLifeDays} days from harvest. Harvested on ${input.harvestDate}, it would ` +
              `reach the hub with ${Math.max(daysLeft, 0)} left, and a hub takes produce with at least ` +
              `${MIN_REMAINING_SHELF_LIFE * 100}% of its life left.`,
            { days_left_at_drop: daysLeft, shelf_life_days: item.shelfLifeDays },
          );
        }
        const nearest = nearestOpenHub(farm);
        if (!nearest) {
          throw new ApiError(409, 'no_hub_with_room', `There is no open hub within ${HUB_SEARCH_KM} km of the farm`, {
            hubs: [],
          });
        }

        const listing: StoredListing = {
          id: nextListingId,
          farmerId: owner.id,
          farm,
          item,
          qtyKg: input.qtyKg,
          pricePerKg: input.pricePerKg,
          harvestDate: input.harvestDate,
          hubId: nearest.hub.id,
          hubName: nearest.hub.name,
          dropFrom: slot.from,
          dropUntil: slot.until,
          createdAt: Date.now(),
          cancelled: false,
        };
        nextListingId += 1;
        listings.push(listing);
        listingIdByKey.set(`${owner.id}:${idempotencyKey}`, listing.id);
        return listingView(listing);
      }),

    cancelListing: (listingId) =>
      delay(() => {
        const owner = farmer();
        const listing = listings.find((candidate) => candidate.id === listingId && candidate.farmerId === owner.id);
        if (!listing) throw new ApiError(404, 'not_found', `Listing ${listingId} does not exist`);
        if (isReceived(listing)) {
          throw new ApiError(409, 'not_cancellable', `Listing ${listingId} is already received`);
        }
        listing.cancelled = true;
        return listingView(listing);
      }),
  };
}
