/**
 * Display formatting only. Never use these for business logic: the backend owns all
 * time arithmetic (time-in-stage, minutes to shift end, ...). Timestamps are shown with
 * a zone name so there is no ambiguity across hospitals in different time zones.
 */

function safeDate(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(iso: string, timeZone?: string | null): string {
  const date = safeDate(iso);
  if (!date) return iso;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
    timeZone: timeZone ?? undefined,
  }).format(date);
}

/** "17:12 EDT" in the given zone (or the viewer's zone). */
export function formatTime(iso: string, timeZone?: string | null, seconds = false): string {
  const date = safeDate(iso);
  if (!date) return iso;
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: seconds ? "2-digit" : undefined,
    timeZoneName: "short",
    timeZone: timeZone ?? undefined,
  }).format(date);
}

export function formatClockTime(date: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function formatDuration(totalMinutes: number): string {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes} min`;
  if (minutes === 0) return `${hours} h`;
  return `${hours} h ${minutes} min`;
}

/** Elapsed seconds as computed by the backend, rendered as "14 min" / "1 h 5 min". */
export function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  return formatDuration(Math.floor(seconds / 60));
}

export function formatCount(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

/** "$800" — an amount the backend computed, shown in its currency. */
export function formatMoney(amount: number, currency = "USD"): string {
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${Math.round(amount)} ${currency}`;
  }
}
