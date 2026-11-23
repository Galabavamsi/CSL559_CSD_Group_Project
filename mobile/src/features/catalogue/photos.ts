/**
 * A photograph for each kind of produce in the catalogue, and for each packaged item a hub stocks, shown when a
 * product has no photo of its own.
 *
 * These are openly licensed photographs from Wikimedia Commons (public domain, CC0 or CC BY), found through the
 * Firecrawl CLI and chosen by eye. Each one's author, licence and source page is in `assets/produce/credits.json`
 * and in `ASSETS.md`. A batch's own photo from the farmer or the hub, when the API sends one, replaces it.
 */
/** Longest names first, so "spring onion" is not taken for "onion". */
/** A bundled image, as Metro's `require` returns it. */
export type BundledImage = number;

const PHOTOS: [string, BundledImage][] = [
  // Packaged goods. "potato chips" has to be met before "potato", and "green peas" is nobody's chilli.
  ['potato chips', require('../../../assets/produce/chips.jpg')],
  ['green peas', require('../../../assets/produce/green-peas.jpg')],
  ['ice cream', require('../../../assets/produce/ice-cream.jpg')],
  ['noodles', require('../../../assets/produce/noodles.jpg')],
  ['paneer', require('../../../assets/produce/paneer.jpg')],
  ['bread', require('../../../assets/produce/bread.jpg')],
  ['sugar', require('../../../assets/produce/sugar.jpg')],
  ['atta', require('../../../assets/produce/atta.jpg')],
  ['curd', require('../../../assets/produce/curd.jpg')],
  ['milk', require('../../../assets/produce/milk.jpg')],
  ['rice', require('../../../assets/produce/rice.jpg')],
  ['soap', require('../../../assets/produce/soap.jpg')],
  ['eggs', require('../../../assets/produce/eggs.jpg')],
  ['oil', require('../../../assets/produce/oil.jpg')],
  ['tea', require('../../../assets/produce/tea.jpg')],
  // Produce.
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
  flour: 'atta',
  yogurt: 'curd',
  yoghurt: 'curd',
  dahi: 'curd',
  crisps: 'potato chips',
};

/** True when `word` begins at the start of a word of `text`: "oil" is in "sunflower oil" but not in "boiled". */
function startsAWord(text: string, word: string): boolean {
  for (let at = text.indexOf(word); at !== -1; at = text.indexOf(word, at + 1)) {
    if (at === 0 || !/[a-z]/.test(text[at - 1])) return true;
  }
  return false;
}

/**
 * The catalogue photo for a product name such as "Tomato", "Bananas (6 pcs)" or "Sunflower oil 1 L", or null when
 * there is none.
 */
export function producePhoto(name: string): BundledImage | null {
  let wanted = name.toLowerCase();
  for (const [other, ours] of Object.entries(ALSO_KNOWN_AS)) {
    if (startsAWord(wanted, other)) wanted = ours;
  }
  const match = PHOTOS.find(([produce]) => startsAWord(wanted, produce));
  return match ? match[1] : null;
}
