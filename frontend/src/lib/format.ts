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

/** "20:00" on a 24-hour clock in the given zone (for mono time readouts). */
export function formatHm(iso: string, timeZone?: string | null): string {
  const date = safeDate(iso);
  if (!date) return iso;
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: timeZone ?? undefined,
  }).format(date);
}

/** Short zone name at that instant, e.g. "EDT" or "PDT". */
export function zoneAbbr(iso: string, timeZone?: string | null): string {
  const date = safeDate(iso);
  if (!date) return "";
  const part = new Intl.DateTimeFormat("en-US", {
    timeZoneName: "short",
    timeZone: timeZone ?? undefined,
  })
    .formatToParts(date)
    .find((p) => p.type === "timeZoneName");
  return part?.value ?? "";
}

/** "Tue 17 Mar" in the given zone. */
export function formatDay(iso: string, timeZone?: string | null): string {
  const date = safeDate(iso);
  if (!date) return iso;
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: timeZone ?? undefined,
  }).format(date);
}
