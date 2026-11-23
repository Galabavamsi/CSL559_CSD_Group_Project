import type MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import type { ComponentProps } from 'react';

import type { Product } from '@/api';
import type { BrandColors } from '@/theme';

export type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];
export type TileKey = keyof BrandColors['tiles'];

export interface Category {
  slug: string;
  label: string;
  icon: IconName;
  tile: TileKey;
}

/** The categories the app knows how to dress. Anything else the API sends still shows, with a neutral look. */
const KNOWN: Category[] = [
  { slug: 'vegetables', label: 'Vegetables', icon: 'carrot', tile: 'vegetables' },
  { slug: 'leafy-greens', label: 'Leafy greens', icon: 'leaf', tile: 'leafyGreens' },
  { slug: 'fruits', label: 'Fruits', icon: 'food-apple', tile: 'fruits' },
  { slug: 'herbs', label: 'Herbs', icon: 'sprout', tile: 'herbs' },
];

function titleCase(slug: string): string {
  const words = slug.replace(/-/g, ' ').trim();
  return words ? words[0].toUpperCase() + words.slice(1) : 'Other';
}

export function categoryOf(slug: string): Category {
  return (
    KNOWN.find((category) => category.slug === slug) ?? {
      slug,
      label: titleCase(slug),
      icon: 'basket-outline',
      tile: 'other',
    }
  );
}

/** The categories present in a product list: known ones first in their fixed order, then the rest by name. */
export function categoriesIn(products: Product[]): Category[] {
  const present = new Set(products.map((product) => product.category));
  const known = KNOWN.filter((category) => present.has(category.slug));
  const others = [...present]
    .filter((slug) => !KNOWN.some((category) => category.slug === slug))
    .sort()
    .map(categoryOf);
  return [...known, ...others];
}

/** Icons that fit a product better than its category's icon, matched on the product's name. */
const ICON_BY_NAME: [RegExp, IconName][] = [
  [/carrot/, 'carrot'],
  [/corn|maize/, 'corn'],
  [/chilli|chili|capsicum|pepper/, 'chili-mild'],
  [/mushroom/, 'mushroom'],
  [/gourd|pumpkin|squash/, 'pumpkin'],
  [/watermelon|melon/, 'fruit-watermelon'],
  [/lemon|lime|orange|mosambi/, 'fruit-citrus'],
  [/grape/, 'fruit-grapes'],
  [/pineapple/, 'fruit-pineapple'],
  [/cherr|berry/, 'fruit-cherries'],
  [/pear|guava|papaya/, 'fruit-pear'],
  [/tomato|apple|pomegranate/, 'food-apple'],
  [/spring onion|lemongrass|chive/, 'grass'],
  [/coriander|mint|curry|basil|parsley|fenugreek/, 'sprout'],
  [/ginger|garlic|turmeric/, 'seed'],
];

/** The icon drawn on a product's art tile when it has no photo. */
export function productIcon(name: string, categorySlug?: string): IconName {
  const lowered = name.toLowerCase();
  const match = ICON_BY_NAME.find(([pattern]) => pattern.test(lowered));
  if (match) return match[1];
  return categorySlug ? categoryOf(categorySlug).icon : 'basket-outline';
}
