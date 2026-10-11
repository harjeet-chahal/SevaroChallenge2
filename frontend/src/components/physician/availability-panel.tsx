"use client";

import { CalendarClock, HandHeart, Info, Loader2, Pencil, Undo2 } from "lucide-react";
import { useState } from "react";

import { TagBadge } from "@/components/shared/status-badges";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Feedback } from "@/components/workflow/feedback";
import { useAction } from "@/components/workflow/use-action";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { availabilityApi } from "@/lib/api/endpoints";
import type { PhysicianAvailabilityPage, VolunteerAvailability } from "@/lib/api/types";
import { formatDateTime, formatDuration, formatTime } from "@/lib/format";
import { ceilMinute, nextDay, zonedParts, zonedToIso } from "@/lib/zoned-time";

interface Draft {
  /** null = a new window; otherwise the window being updated. */
  id: string | null;
  version: number;
  date: string;
  from: string;
  until: string;
}

const PRESET_HOURS = [2, 4, 6];

const PHASE: Record<
  VolunteerAvailability["phase"],
  { label: string; tone: "success" | "neutral" }
> = {
  current: { label: "Shared · available now", tone: "success" },
  upcoming: { label: "Shared", tone: "success" },
  past: { label: "Ended", tone: "neutral" },
  withdrawn: { label: "Withdrawn", tone: "neutral" },
};

function zoneName(timeZone: string, at: string): string {
  const part = new Intl.DateTimeFormat(undefined, { timeZone, timeZoneName: "short" })
    .formatToParts(new Date(at))
    .find((p) => p.type === "timeZoneName");
  return part?.value ?? timeZone;
}

/** The typed window as instants; an "until" at or before "from" ends the next day. */
function toWindow(d: Draft, tz: string) {
  const overnight = d.until <= d.from;
  const start = zonedToIso(d.date, d.from, tz);
  const end = zonedToIso(overnight ? nextDay(d.date) : d.date, d.until, tz);
  if (!start || !end) return null;
  const minutes = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000);
  return { start, end, overnight, minutes };
}

function presetDraft(page: PhysicianAvailabilityPage, hours: number, base?: Draft): Draft {
  const startIso = ceilMinute(page.simulation_time);
  const endIso = new Date(new Date(startIso).getTime() + hours * 3600_000).toISOString();
  const start = zonedParts(startIso, page.timezone);
  return {
    id: base?.id ?? null,
    version: base?.version ?? 0,
    date: start.date,
    from: start.time,
    until: zonedParts(endIso, page.timezone).time,
  };
}

function editDraft(item: VolunteerAvailability): Draft {
  const start = zonedParts(item.start_at, item.timezone);
  return {
    id: item.id,
    version: item.version,
    date: start.date,
    from: start.time,
    until: zonedParts(item.end_at, item.timezone).time,
  };
}

function WindowForm({
  page,
  draft,
  onChange,
  onCancel,
  onSubmit,
  pending,
}: {
  page: PhysicianAvailabilityPage;
  draft: Draft;
  onChange: (d: Draft) => void;
  onCancel: () => void;
  onSubmit: () => void;
  pending: boolean;
}) {
  const tz = page.timezone;
  const window = toWindow(draft, tz);
  const short = window !== null && window.minutes < page.min_useful_window_minutes;
  const field = "h-10 text-base";
  return (
    <form
      className="space-y-3 rounded-xl border bg-muted/30 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <fieldset className="space-y-3">
        <legend className="text-sm font-semibold text-navy">
          {draft.id ? "Update your availability" : "When could you cover an extra shift?"}
        </legend>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Quick choices">
          {PRESET_HOURS.map((h) => (
            <Button
              key={h}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onChange(presetDraft(page, h, draft))}
            >
              Next {h} h
            </Button>
          ))}
        </div>
        <div className="grid grid-cols-1 gap-2 min-[380px]:grid-cols-3">
          <label className="space-y-1 text-xs font-medium text-muted-foreground">
            Date
            <Input
              type="date"
              required
              className={field}
              value={draft.date}
              onChange={(e) => onChange({ ...draft, date: e.target.value })}
            />
          </label>
          <label className="space-y-1 text-xs font-medium text-muted-foreground">
            From
            <Input
              type="time"
              required
              className={field}
              value={draft.from}
              onChange={(e) => onChange({ ...draft, from: e.target.value })}
            />
          </label>
          <label className="space-y-1 text-xs font-medium text-muted-foreground">
            Until
            <Input
              type="time"
              required
              className={field}
              value={draft.until}
              onChange={(e) => onChange({ ...draft, until: e.target.value })}
            />
          </label>
        </div>
        <p className="text-xs text-muted-foreground">
          {window
            ? `${formatDuration(window.minutes)} window${window.overnight ? ", ending the next day" : ""}`
            : "Enter a date and times"}{" "}
          · times in {zoneName(tz, page.simulation_time)} (your hospital&apos;s time zone)
        </p>
        {short ? (
          <p className="rounded-md border border-warning-border bg-warning-soft p-2 text-xs text-warning">
            Shorter than {formatDuration(page.min_useful_window_minutes)}: offers need 2 h of
            coverage after you come online, so this window can&apos;t be matched to an offer.
          </p>
        ) : null}
      </fieldset>
      <div className="flex gap-3">
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="h-11 shrink-0 px-4 text-base"
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button
          type="submit"
          size="lg"
          className="h-11 min-w-0 flex-1 text-base"
          disabled={pending || window === null || window.minutes <= 0}
        >
          {pending ? <Loader2 className="animate-spin" aria-hidden /> : <HandHeart aria-hidden />}
          {draft.id ? "Save changes" : "Share availability"}
        </Button>
      </div>
    </form>
  );
}

function WindowItem({
  item,
  busy,
  onEdit,
  onWithdraw,
}: {
  item: VolunteerAvailability;
  busy: boolean;
  onEdit: () => void;
  onWithdraw: () => void;
}) {
  const tz = item.timezone;
  const phase = PHASE[item.phase];
  return (
    <li className="space-y-2 rounded-xl border bg-card p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 font-semibold text-foreground">
          <CalendarClock className="size-4 text-muted-foreground" aria-hidden />
          {formatTime(item.start_at, tz)} – {formatTime(item.end_at, tz)}
        </p>
        <TagBadge tone={phase.tone}>{phase.label}</TagBadge>
      </div>
      <p className="text-sm text-muted-foreground">
        {formatDateTime(item.start_at, tz)} · {formatDuration(item.duration_minutes)}
      </p>
      <p className="text-xs text-muted-foreground">{item.message}</p>
      {item.can_update || item.can_withdraw ? (
        <div className="grid grid-cols-2 gap-3">
          <Button variant="outline" className="h-10" disabled={busy || !item.can_update} onClick={onEdit}>
            <Pencil aria-hidden />
            Update
          </Button>
          <Button
            variant="outline"
            className="h-10"
            disabled={busy || !item.can_withdraw}
            onClick={onWithdraw}
          >
            <Undo2 aria-hidden />
            Withdraw
          </Button>
        </div>
      ) : null}
    </li>
  );
}

/**
 * "I'm Available": the physician tells the coordination team when they could cover an
 * extra shift. It never assigns a shift — the coordinator's ranking prefers them, a
 * clinical lead still approves any offer, and the physician still accepts or declines it.
 */
export function AvailabilityPanel({
  physicianId,
  versions,
}: {
  physicianId: string;
  versions: string;
}) {
  const resource = useKeyedResource(`availability|${physicianId}|${versions}`, (signal) =>
    availabilityApi.mine(physicianId, signal).then((page) => ({ physicianId, page })),
  );
  const page = resource.data?.physicianId === physicianId ? resource.data.page : null;
  // A draft belongs to the physician it was started for; switching user discards it.
  const [editing, setEditing] = useState<{ physicianId: string; draft: Draft } | null>(null);
  const draft = editing?.physicianId === physicianId ? editing.draft : null;
  const setDraft = (d: Draft | null) => setEditing(d ? { physicianId, draft: d } : null);
  const { pending, feedback, run, clear } = useAction();

  const shared = page?.items.filter((i) => i.phase === "current" || i.phase === "upcoming") ?? [];
  const history = page?.items.filter((i) => i.phase === "past" || i.phase === "withdrawn") ?? [];

  const submit = () => {
    if (!page || !draft) return;
    const window = toWindow(draft, page.timezone);
    if (!window) return;
    void run("save", async () => {
      if (draft.id) {
        await availabilityApi.update(physicianId, draft.id, window.start, window.end, draft.version);
        setDraft(null);
        return "Availability updated. You have still not been assigned a shift.";
      }
      await availabilityApi.create(physicianId, window.start, window.end);
      setDraft(null);
      return "Thanks — your availability is shared with the coordination team. You have not been assigned a shift; if one is needed, an offer will appear below to accept or decline.";
    });
  };

  return (
    <section
      aria-labelledby="availability-title"
      className="space-y-3 rounded-2xl border bg-card p-4 shadow-xs sm:p-5"
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="space-y-0.5">
          <h2 id="availability-title" className="flex items-center gap-1.5 text-lg font-semibold text-navy">
            <HandHeart className="size-5 text-primary" aria-hidden />
            Extra shift availability
          </h2>
          <p className="text-sm text-muted-foreground">
            Let the coordination team know when you could cover an extra shift.
          </p>
        </div>
        {shared.length ? <TagBadge tone="success">Shared</TagBadge> : null}
      </header>

      {resource.error && !page ? (
        <p className="text-sm text-critical">{resource.error}</p>
      ) : !page ? (
        <p className="text-sm text-muted-foreground">Loading availability…</p>
      ) : draft ? (
        <WindowForm
          page={page}
          draft={draft}
          onChange={setDraft}
          onCancel={() => setDraft(null)}
          onSubmit={submit}
          pending={pending === "save"}
        />
      ) : (
        <Button
          size="lg"
          className="h-11 w-full text-base"
          disabled={pending !== null}
          onClick={() => {
            clear();
            setDraft(presetDraft(page, 4));
          }}
        >
          <HandHeart aria-hidden />
          I&apos;m Available
        </Button>
      )}

      <p className="flex gap-2 rounded-md border border-info-border bg-info-soft p-2.5 text-xs text-info">
        <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
        Sharing availability does not assign you a shift. If cover is needed, a coordinator may
        send you an offer — approved by a clinical lead first — that you can accept or decline.
      </p>

      <Feedback feedback={feedback} />

      {page && page.notes.length && (draft || page.opted_in !== true) ? (
        <ul className="space-y-1 text-xs text-muted-foreground">
          {page.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}

      {shared.length ? (
        <ul className="space-y-2" aria-label="Your shared availability">
          {shared.map((item) => (
            <WindowItem
              key={item.id}
              item={item}
              busy={pending !== null}
              onEdit={() => {
                clear();
                setDraft(editDraft(item));
              }}
              onWithdraw={() =>
                void run(`withdraw:${item.id}`, async () => {
                  await availabilityApi.withdraw(physicianId, item.id);
                  if (draft?.id === item.id) setDraft(null);
                  return "Availability withdrawn. Coordinators no longer see this window.";
                })
              }
            />
          ))}
        </ul>
      ) : null}

      {history.length ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            Past and withdrawn ({history.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {history.map((item) => (
              <WindowItem key={item.id} item={item} busy onEdit={() => {}} onWithdraw={() => {}} />
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
