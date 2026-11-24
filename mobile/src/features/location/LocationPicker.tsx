import type { ComponentType } from 'react';

import type { City } from '@/api';

import { PresetLocationPicker } from './PresetLocationPicker';

/** A point the customer chose, with the words to show for it. */
export interface PickedPoint {
  label: string;
  lat: number;
  lng: number;
}

/**
 * What the delivery-location screen needs from a picker: show the cities, let the customer choose a point,
 * report it. The screen does the rest (asks the API whether the point is served, shows the hub and ETA).
 */
export interface LocationPickerProps {
  cities: City[];
  /** City to show first, by slug; the first city when null. */
  initialCitySlug: string | null;
  value: PickedPoint | null;
  onChange: (point: PickedPoint) => void;
}

/**
 * THE SEAM FOR THE MAP. Today the picker is a GPS button plus a list of areas, with no maps SDK.
 * A map pin-drop (Amazon Location tiles drawn with MapLibre, docs/DESIGN.md section 1.2) is a second component
 * with these same props (`MapLocationPicker`: a map centred on
 * `value` or the city, a fixed pin, `onChange` when the map settles). Point this constant at it and the
 * location screen needs no other change.
 */
export const LocationPicker: ComponentType<LocationPickerProps> = PresetLocationPicker;
