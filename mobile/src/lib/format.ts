/** Digits grouped the Indian way: 1,20,000. */
function grouped(whole: number): string {
  const digits = String(whole);
  if (digits.length <= 3) return digits;
  const lastThree = digits.slice(-3);
  const rest = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',');
  return `${rest},${lastThree}`;
}

/** "₹24" for whole rupees, "₹24.50" otherwise, "₹12,000" for large amounts. */
export function formatRupees(amount: number): string {
  const paise = Math.round(amount * 100);
  const whole = Math.floor(paise / 100);
  const fraction = paise % 100;
  return `₹${grouped(whole)}${fraction === 0 ? '' : `.${String(fraction).padStart(2, '0')}`}`;
}

/** "48 kg" or "2.5 kg": at most one decimal, and none when it would be zero. */
export function formatKg(kilograms: number): string {
  return `${Math.round(kilograms * 10) / 10} kg`;
}

/** "6.4 km" or "12 km": at most one decimal, and none when it would be zero. */
export function formatKm(kilometres: number): string {
  return `${Math.round(kilometres * 10) / 10} km`;
}

/** A number with its noun: "1 bag", "3 bags", "1 try", "4 tries". */
export function countOf(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}
