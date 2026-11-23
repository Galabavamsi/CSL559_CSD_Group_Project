import type { City } from '@/api';

export interface PresetArea {
  name: string;
  lat: number;
  lng: number;
}

/**
 * Well-known areas of each city, for picking a delivery point without a map. The coordinates are approximate
 * area centres. Whether an area is served is always the API's answer, never assumed here.
 */
const AREAS_BY_CITY: Record<string, PresetArea[]> = {
  bhilai: [
    { name: 'IIT Bhilai', lat: 21.2444, lng: 81.3176 },
    { name: 'Civic Centre', lat: 21.1938, lng: 81.3509 },
    { name: 'Supela', lat: 21.207, lng: 81.344 },
    { name: 'Nehru Nagar', lat: 21.209, lng: 81.326 },
    { name: 'Smriti Nagar', lat: 21.219, lng: 81.318 },
    { name: 'Risali', lat: 21.165, lng: 81.34 },
    { name: 'Durg Station Road', lat: 21.1904, lng: 81.2849 },
    { name: 'Kumhari', lat: 21.266, lng: 81.519 },
  ],
  bangalore: [
    { name: 'MG Road', lat: 12.9756, lng: 77.605 },
    { name: 'Indiranagar', lat: 12.9719, lng: 77.6412 },
    { name: 'Koramangala', lat: 12.9352, lng: 77.6245 },
    { name: 'HSR Layout', lat: 12.9116, lng: 77.6474 },
    { name: 'Hebbal', lat: 13.0358, lng: 77.597 },
    { name: 'Whitefield', lat: 12.9698, lng: 77.75 },
  ],
};

/** The areas offered for a city. A city this file does not know yet still gets its centre. */
export function presetAreasOf(city: City): PresetArea[] {
  return AREAS_BY_CITY[city.slug] ?? [{ name: `${city.name} centre`, lat: city.lat, lng: city.lng }];
}
