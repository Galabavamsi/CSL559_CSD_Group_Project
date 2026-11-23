/** Demo data for mock mode: two cities, their hubs, and what local farmers dropped off this week. */
import type { City, Grade, Hub } from '../types';

export const CITIES: City[] = [
  { slug: 'bhilai', name: 'Bhilai', tier: 2, lat: 21.1938, lng: 81.3509, radiusKm: 8, hubRadiusKm: 3, hubs: 4 },
  { slug: 'bangalore', name: 'Bangalore', tier: 1, lat: 12.9716, lng: 77.5946, radiusKm: 18, hubRadiusKm: 2, hubs: 4 },
];

export const HUBS: Hub[] = [
  { id: 1, name: 'Civic Centre Hub', lat: 21.1938, lng: 81.3509, radiusKm: 4, status: 'open', city: 'bhilai' },
  { id: 2, name: 'Nehru Nagar Hub', lat: 21.209, lng: 81.326, radiusKm: 3, status: 'open', city: 'bhilai' },
  { id: 3, name: 'Durg Hub', lat: 21.1904, lng: 81.2849, radiusKm: 3, status: 'open', city: 'bhilai' },
  { id: 8, name: 'IIT Bhilai Hub', lat: 21.24, lng: 81.317, radiusKm: 3, status: 'open', city: 'bhilai' },
  { id: 4, name: 'MG Road Hub', lat: 12.9716, lng: 77.5946, radiusKm: 3.5, status: 'open', city: 'bangalore' },
  { id: 5, name: 'Indiranagar Hub', lat: 12.9719, lng: 77.6412, radiusKm: 3, status: 'open', city: 'bangalore' },
  { id: 6, name: 'Koramangala Hub', lat: 12.9352, lng: 77.6245, radiusKm: 4, status: 'open', city: 'bangalore' },
  { id: 7, name: 'Hebbal Hub', lat: 13.035, lng: 77.597, radiusKm: 3, status: 'busy', city: 'bangalore' },
];

/** Farms that supply each city, indexed by `CatalogueItem.farm`. */
export const FARMS: Record<string, string[]> = {
  bhilai: [
    'Sahu Farm, Patan',
    'Verma Vegetable Farm, Dhamdha',
    'Chandrakar Orchard, Gunderdehi',
    'Nirmalkar Greens, Utai',
  ],
  bangalore: [
    'Gowda Farms, Hoskote',
    'Reddy Vegetable Farm, Malur',
    'Nandi Orchards, Chikkaballapur',
    'Devanahalli Greens, Devanahalli',
  ],
};

/** What things cost in a tier-1 city compared with the base (tier-2) price. */
export const CITY_PRICE_FACTOR: Record<string, number> = { bhilai: 1, bangalore: 1.2 };

/** Share of the price kept when a batch has one day left. */
export const MARKDOWN_FACTOR = 0.7;

export interface CatalogueItem {
  id: number;
  name: string;
  category: 'vegetables' | 'leafy-greens' | 'fruits' | 'herbs';
  unitLabel: string;
  /** Rupees per unit in Bhilai. */
  basePrice: number;
  grade: Grade;
  harvestedDaysAgo: number;
  /** 1 means the batch has one day left and is sold at the markdown price. */
  useByInDays: number;
  farm: 0 | 1 | 2 | 3;
  /** Units a hub starts with; each hub varies a little around it. 0 is out of stock everywhere. */
  stock: number;
}

export const CATALOGUE: CatalogueItem[] = [
  { id: 1, name: 'Tomato', category: 'vegetables', unitLabel: '500 g pack', basePrice: 24, grade: 'A', harvestedDaysAgo: 1, useByInDays: 4, farm: 0, stock: 30 },
  { id: 2, name: 'Onion', category: 'vegetables', unitLabel: '1 kg pack', basePrice: 38, grade: 'A', harvestedDaysAgo: 5, useByInDays: 12, farm: 1, stock: 40 },
  { id: 3, name: 'Potato', category: 'vegetables', unitLabel: '1 kg pack', basePrice: 32, grade: 'B', harvestedDaysAgo: 6, useByInDays: 14, farm: 1, stock: 36 },
  { id: 4, name: 'Cauliflower', category: 'vegetables', unitLabel: '1 piece · 400–600 g', basePrice: 35, grade: 'A', harvestedDaysAgo: 1, useByInDays: 3, farm: 0, stock: 14 },
  { id: 5, name: "Lady's finger", category: 'vegetables', unitLabel: '250 g pack', basePrice: 22, grade: 'A', harvestedDaysAgo: 1, useByInDays: 2, farm: 0, stock: 18 },
  { id: 6, name: 'Brinjal', category: 'vegetables', unitLabel: '500 g pack', basePrice: 28, grade: 'B', harvestedDaysAgo: 3, useByInDays: 1, farm: 1, stock: 8 },
  { id: 7, name: 'Carrot', category: 'vegetables', unitLabel: '500 g pack', basePrice: 34, grade: 'A', harvestedDaysAgo: 2, useByInDays: 6, farm: 1, stock: 20 },
  { id: 8, name: 'Green chilli', category: 'vegetables', unitLabel: '100 g pack', basePrice: 12, grade: 'A', harvestedDaysAgo: 1, useByInDays: 5, farm: 0, stock: 25 },
  { id: 9, name: 'Bottle gourd', category: 'vegetables', unitLabel: '1 piece · 600–800 g', basePrice: 30, grade: 'B', harvestedDaysAgo: 2, useByInDays: 4, farm: 0, stock: 10 },
  { id: 10, name: 'Sweet corn', category: 'vegetables', unitLabel: '2 pieces', basePrice: 36, grade: 'A', harvestedDaysAgo: 2, useByInDays: 1, farm: 1, stock: 6 },
  { id: 11, name: 'Spinach', category: 'leafy-greens', unitLabel: '1 bunch · about 250 g', basePrice: 18, grade: 'A', harvestedDaysAgo: 0, useByInDays: 2, farm: 3, stock: 16 },
  { id: 12, name: 'Fenugreek leaves', category: 'leafy-greens', unitLabel: '1 bunch', basePrice: 20, grade: 'A', harvestedDaysAgo: 1, useByInDays: 1, farm: 3, stock: 7 },
  { id: 13, name: 'Red amaranth', category: 'leafy-greens', unitLabel: '1 bunch', basePrice: 15, grade: 'B', harvestedDaysAgo: 0, useByInDays: 2, farm: 3, stock: 12 },
  { id: 14, name: 'Cabbage', category: 'leafy-greens', unitLabel: '1 piece · 500–700 g', basePrice: 28, grade: 'A', harvestedDaysAgo: 2, useByInDays: 6, farm: 0, stock: 15 },
  { id: 15, name: 'Spring onion', category: 'leafy-greens', unitLabel: '1 bunch', basePrice: 16, grade: 'A', harvestedDaysAgo: 1, useByInDays: 3, farm: 3, stock: 0 },
  { id: 16, name: 'Banana', category: 'fruits', unitLabel: '6 pieces', basePrice: 36, grade: 'A', harvestedDaysAgo: 2, useByInDays: 4, farm: 2, stock: 22 },
  { id: 17, name: 'Papaya', category: 'fruits', unitLabel: '1 piece · 800 g–1 kg', basePrice: 48, grade: 'A', harvestedDaysAgo: 2, useByInDays: 3, farm: 2, stock: 9 },
  { id: 18, name: 'Guava', category: 'fruits', unitLabel: '500 g pack', basePrice: 45, grade: 'B', harvestedDaysAgo: 1, useByInDays: 4, farm: 2, stock: 12 },
  { id: 19, name: 'Lemon', category: 'fruits', unitLabel: '4 pieces', basePrice: 20, grade: 'A', harvestedDaysAgo: 3, useByInDays: 9, farm: 2, stock: 30 },
  { id: 20, name: 'Pomegranate', category: 'fruits', unitLabel: '2 pieces · 350–450 g', basePrice: 90, grade: 'A', harvestedDaysAgo: 3, useByInDays: 7, farm: 2, stock: 2 },
  { id: 21, name: 'Watermelon', category: 'fruits', unitLabel: '1 piece · 2–3 kg', basePrice: 70, grade: 'B', harvestedDaysAgo: 2, useByInDays: 5, farm: 2, stock: 0 },
  { id: 22, name: 'Coriander', category: 'herbs', unitLabel: '1 bunch', basePrice: 10, grade: 'A', harvestedDaysAgo: 0, useByInDays: 2, farm: 3, stock: 28 },
  { id: 23, name: 'Mint', category: 'herbs', unitLabel: '1 bunch', basePrice: 10, grade: 'A', harvestedDaysAgo: 1, useByInDays: 1, farm: 3, stock: 9 },
  { id: 24, name: 'Curry leaves', category: 'herbs', unitLabel: '1 bunch', basePrice: 8, grade: 'A', harvestedDaysAgo: 1, useByInDays: 5, farm: 3, stock: 18 },
  { id: 25, name: 'Ginger', category: 'herbs', unitLabel: '100 g pack', basePrice: 16, grade: 'B', harvestedDaysAgo: 7, useByInDays: 15, farm: 1, stock: 20 },
];

/** Names the mock gives to the delivery agent of an order. */
export const AGENT_NAMES = ['Ravi Yadav', 'Imran Khan', 'Suresh Nayak', 'Manoj Kumar'];

/** The sign-in code the mock accepts for every address. Shown on the sign-in screens in mock mode. */
export const MOCK_OTP_CODE = '123456';
