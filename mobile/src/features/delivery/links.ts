import { Linking, Platform } from 'react-native';

import type { DeliveryAddress } from '@/api';

/** A map page any browser can show, with a marker on the point. */
function webMapUrl({ lat, lng }: DeliveryAddress): string {
  return `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`;
}

/** The link that opens the phone's own maps app with a pin on the address; in a browser, a map page. */
function mapsUrl(address: DeliveryAddress): string {
  const { lat, lng } = address;
  // Brackets close the pin's name in a geo link, so a name may not carry its own.
  const name = encodeURIComponent(address.label.replace(/[()]/g, ' '));
  if (Platform.OS === 'android') return `geo:${lat},${lng}?q=${lat},${lng}(${name})`;
  if (Platform.OS === 'ios') return `http://maps.apple.com/?ll=${lat},${lng}&q=${name}`;
  return webMapUrl(address);
}

async function open(url: string): Promise<boolean> {
  try {
    await Linking.openURL(url);
    return true;
  } catch {
    return false;
  }
}

/** Show the address in a maps app. A phone with no maps app gets the map page instead. False when neither opened. */
export async function openInMaps(address: DeliveryAddress): Promise<boolean> {
  return (await open(mapsUrl(address))) || (Platform.OS !== 'web' && (await open(webMapUrl(address))));
}

/** Start a call in the phone's dialler. False when the device cannot make calls. */
export function callNumber(phone: string): Promise<boolean> {
  return open(`tel:${phone.replace(/[^\d+]/g, '')}`);
}
