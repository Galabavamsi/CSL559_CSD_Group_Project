import type { CartLine, OrderLine, Product } from '@/api/types';

/** Rupees a customer pays for one unit today: the markdown price when the batch is marked down. */
export function unitPrice(product: Product): number {
  return isRescueDeal(product) ? (product.markdownPrice as number) : product.price;
}

/** A batch with one day left, sold below its usual price so it is eaten instead of thrown away. */
export function isRescueDeal(product: Product): boolean {
  return product.markdownPrice !== null && product.markdownPrice < product.price;
}

/** Whole percent off, for the badge on a rescue deal. */
export function discountPercent(product: Product): number {
  return isRescueDeal(product) ? Math.round((1 - (product.markdownPrice as number) / product.price) * 100) : 0;
}

export interface Bill {
  lines: OrderLine[];
  /** Cart lines whose product the hub no longer lists. They are left out of the totals. */
  missingProductIds: number[];
  itemTotal: number;
  savings: number;
  deliveryFee: number;
  total: number;
}

/**
 * Pooled delivery carries no fee in this version: the API has no delivery-fee rule yet.
 * This is the one place to change when it gets one.
 */
const DELIVERY_FEE = 0;

/** Price a cart against a hub's product list. */
export function computeBill(cart: CartLine[], products: Product[]): Bill {
  const byId = new Map(products.map((product) => [product.id, product]));
  const lines: OrderLine[] = [];
  const missingProductIds: number[] = [];
  let fullPriceTotal = 0;

  for (const { productId, quantity } of cart) {
    const product = byId.get(productId);
    if (!product) {
      missingProductIds.push(productId);
      continue;
    }
    lines.push({
      productId,
      name: product.name,
      unitLabel: product.unitLabel,
      quantity,
      unitPrice: unitPrice(product),
    });
    fullPriceTotal += product.price * quantity;
  }

  const itemTotal = lines.reduce((sum, line) => sum + line.unitPrice * line.quantity, 0);
  const deliveryFee = lines.length > 0 ? DELIVERY_FEE : 0;
  return {
    lines,
    missingProductIds,
    itemTotal,
    savings: fullPriceTotal - itemTotal,
    deliveryFee,
    total: itemTotal + deliveryFee,
  };
}
