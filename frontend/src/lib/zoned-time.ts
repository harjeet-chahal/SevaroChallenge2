/**
 * Input helpers for wall-clock times typed in a given IANA zone (e.g. a physician picking
 * "18:30–22:30" in their hospital's zone). These only translate what the user typed into an
 * exact instant for the API; every rule about the window is checked by the backend.
 */

function partsIn(utcMs: number, timeZone: string): Record<string, string> {
  const format = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return Object.fromEntries(format.formatToParts(new Date(utcMs)).map((p) => [p.type, p.value]));
}

/** Minutes the zone is ahead of UTC at this instant. */
function offsetMinutes(utcMs: number, timeZone: string): number {
  const p = partsIn(utcMs, timeZone);
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  return Math.round((wall - utcMs) / 60000);
}

/** An instant as the date ("2030-09-10") and time ("18:35") shown in ``timeZone``. */
export function zonedParts(iso: string, timeZone: string): { date: string; time: string } {
  const p = partsIn(new Date(iso).getTime(), timeZone);
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}

/** A wall-clock date + time in ``timeZone`` as an ISO instant (UTC), or null if invalid. */
export function zonedToIso(date: string, time: string, timeZone: string): string | null {
  const [y, mo, d] = date.split("-").map(Number);
  const [h, mi] = time.split(":").map(Number);
  if ([y, mo, d, h, mi].some((n) => n === undefined || Number.isNaN(n))) return null;
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  // Two passes settle the offset across a daylight-saving change.
  let utc = guess - offsetMinutes(guess, timeZone) * 60000;
  utc = guess - offsetMinutes(utc, timeZone) * 60000;
  return new Date(utc).toISOString();
}

/** The next calendar day of a "YYYY-MM-DD" date. */
export function nextDay(date: string): string {
  const [y, mo, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, mo - 1, d + 1)).toISOString().slice(0, 10);
}

/** Round an ISO instant up to the next whole minute. */
export function ceilMinute(iso: string): string {
  const ms = new Date(iso).getTime();
  return new Date(Math.ceil(ms / 60000) * 60000).toISOString();
}
