const ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'; // no 0/O or 1/I, so it can be read aloud

/**
 * A new order id, for example "F2H-7K2M9QX4". The app makes it before asking for a hold, because the API uses
 * it as the idempotency key: a retried request with the same id returns the same hold.
 */
export function newOrderId(): string {
  return `F2H-${randomCode(8)}`;
}

/** A key for one attempt at something that must not happen twice (the API's Idempotency-Key header). */
export function newIdempotencyKey(): string {
  return `${Date.now().toString(36)}-${randomCode(12)}`;
}

function randomCode(length: number): string {
  let code = '';
  for (let i = 0; i < length; i += 1) code += ALPHABET[Math.floor(Math.random() * ALPHABET.length)];
  return code;
}
