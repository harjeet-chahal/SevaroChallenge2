/**
 * Display formatting only. Never use these for business logic: the backend owns all
 * time arithmetic (time-in-stage, minutes to shift end, ...). Timestamps are shown with
 * a zone name so there is no ambiguity across hospitals in different time zones.
 */

function safeDate(iso: string): Date | null {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Parts in en-US so every view reads the same regardless of browser locale: 24-hour digits,
 * "Sep" and US zone abbreviations ("EDT", "CDT") where the zone has one.
 */
function zonedFormat(
  date: Date,
  timeZone: string | null | undefined,
  options: Intl.DateTimeFormatOptions,
): (type: Intl.DateTimeFormatPartTypes) => string {
  const parts = new Intl.DateTimeFormat("en-US", {
    ...options,
    hourCycle: "h23",
    timeZoneName: "short",
    timeZone: timeZone ?? undefined,
  }).formatToParts(date);
  return (type) => parts.find((p) => p.type === type)?.value ?? "";
}

/** "Sep 10, 18:35 EDT" in the given zone (or the viewer's zone). */
export function formatDateTime(iso: string, timeZone?: string | null): string {
  const date = safeDate(iso);
  if (!date) return iso;
  const part = zonedFormat(date, timeZone, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${part("month")} ${part("day")}, ${part("hour")}:${part("minute")} ${part("timeZoneName")}`;
}

/** "17:12 EDT" in the given zone (or the viewer's zone). */
export function formatTime(iso: string, timeZone?: string | null, seconds = false): string {
  const date = safeDate(iso);
  if (!date) return iso;
  const part = zonedFormat(date, timeZone, {
    hour: "2-digit",
    minute: "2-digit",
    second: seconds ? "2-digit" : undefined,
  });
  const time = `${part("hour")}:${part("minute")}${seconds ? `:${part("second")}` : ""}`;
  return `${time} ${part("timeZoneName")}`;
}

export function formatClockTime(date: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
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

/** The simulation clock as a monitor readout: "18:20", "EDT" and "Tue 17 Mar". */
export function clockParts(
  iso: string,
  timeZone?: string | null,
): { time: string; zone: string; day: string } | null {
  const date = safeDate(iso);
  if (!date) return null;
  const part = zonedFormat(date, timeZone, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  return {
    time: `${part("hour")}:${part("minute")}`,
    zone: part("timeZoneName"),
    day: `${part("weekday")} ${part("day")} ${part("month")}`,
  };
}

/** Backend-computed elapsed seconds with seconds shown: "12 min 45 s", "1 h 5 min". */
export function formatElapsedPrecise(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s >= 3600) return formatDuration(Math.floor(s / 60));
  if (s < 60) return `${s} s`;
  const rest = s % 60;
  return rest ? `${Math.floor(s / 60)} min ${rest} s` : `${Math.floor(s / 60)} min`;
}
