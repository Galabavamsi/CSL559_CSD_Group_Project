/**
 * A photograph for each kind of produce in the catalogue, shown when a product has no photo of its own.
 *
 * These are openly licensed photographs from Wikimedia Commons (public domain, CC0 or CC BY), found through the
 * Firecrawl CLI and chosen by eye. Each one's author, licence and source page is in `assets/produce/credits.json`
 * and in `ASSETS.md`. A batch's own photo from the farmer or the hub, when the API sends one, replaces it.
 */
/** Longest names first, so "spring onion" is not taken for "onion". */
/** A bundled image, as Metro's `require` returns it. */
export type BundledImage = number;

const PHOTOS: [string, BundledImage][] = [
  ['fenugreek leaves', require('../../../assets/produce/fenugreek-leaves.jpg')],
  ['bottle gourd', require('../../../assets/produce/bottle-gourd.jpg')],
  ['curry leaves', require('../../../assets/produce/curry-leaves.jpg')],
  ['green chilli', require('../../../assets/produce/green-chilli.jpg')],
  ['red amaranth', require('../../../assets/produce/red-amaranth.jpg')],
  ['spring onion', require('../../../assets/produce/spring-onion.jpg')],
  ['cauliflower', require('../../../assets/produce/cauliflower.jpg')],
  ['pomegranate', require('../../../assets/produce/pomegranate.jpg')],
  ['sweet corn', require('../../../assets/produce/sweet-corn.jpg')],
  ['watermelon', require('../../../assets/produce/watermelon.jpg')],
  ['coriander', require('../../../assets/produce/coriander.jpg')],
  ['brinjal', require('../../../assets/produce/brinjal.jpg')],
  ['cabbage', require('../../../assets/produce/cabbage.jpg')],
  ['spinach', require('../../../assets/produce/spinach.jpg')],
  ['banana', require('../../../assets/produce/banana.jpg')],
  ['carrot', require('../../../assets/produce/carrot.jpg')],
  ['ginger', require('../../../assets/produce/ginger.jpg')],
  ['papaya', require('../../../assets/produce/papaya.jpg')],
  ['potato', require('../../../assets/produce/potato.jpg')],
  ['tomato', require('../../../assets/produce/tomato.jpg')],
  ['guava', require('../../../assets/produce/guava.jpg')],
  ['lemon', require('../../../assets/produce/lemon.jpg')],
  ['onion', require('../../../assets/produce/onion.jpg')],
  ['mint', require('../../../assets/produce/mint.jpg')],
  ['okra', require('../../../assets/produce/okra.jpg')],
];

/** Names the backend or a farmer may use for the same produce. */
const ALSO_KNOWN_AS: Record<string, string> = {
  eggplant: 'brinjal',
  aubergine: 'brinjal',
  'lady finger': 'okra',
  bhindi: 'okra',
  'green chili': 'green chilli',
  cilantro: 'coriander',
  methi: 'fenugreek leaves',
  scallion: 'spring onion',
  corn: 'sweet corn',
  lauki: 'bottle gourd',
};

/** The catalogue photo for a product name such as "Tomato" or "Tomato, 500 g", or null when there is none. */
export function producePhoto(name: string): BundledImage | null {
  let wanted = name.toLowerCase();
  for (const [other, ours] of Object.entries(ALSO_KNOWN_AS)) {
    if (wanted.includes(other)) wanted = ours;
  }
  const match = PHOTOS.find(([produce]) => wanted.includes(produce));
  return match ? match[1] : null;
}
