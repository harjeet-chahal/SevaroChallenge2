"use client";

import { useRef, useState } from "react";
import { apiRequest } from "@/lib/api/client";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { formatDateTime } from "@/lib/format";

type Availability = { enabled: boolean; windows: { start: string; end: string }[] };

export function ExtraAvailability({ physicianId }: { physicianId: string }) {
  const { config, refresh } = useSystemStatus();
  const resource = useKeyedResource(`${physicianId}|${config?.data_version}`, (signal) =>
    apiRequest<Availability>("/api/offers/extra-availability", { role: "physician", actorId: physicianId, signal }),
  );
  const [draft, setDraft] = useState<Availability | null>(null);
  const startInput = useRef<HTMLInputElement>(null);
  const endInput = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const value = draft ?? resource.data;
  if (!value) return <p className="text-sm">{resource.error ?? "Loading extra-shift availability…"}</p>;
  const field = "min-h-11 w-full rounded-lg border border-border-strong bg-card px-3";
  return <section className="space-y-3 rounded-xl border border-border p-4">
    <h2 className="text-lg font-semibold">Extra-shift availability</h2>
    <p className="text-sm text-muted-foreground">Tell the team when you can work extra shifts. Times use this device’s local timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone}). Use dates matching the simulation clock.</p>
    <label className="flex gap-2 items-center"><input type="checkbox" checked={value.enabled} onChange={e => setDraft({ ...value, enabled: e.target.checked })} />Use my declared availability windows</label>
    <p className="text-xs text-muted-foreground">When enabled, offers must fit entirely inside a window. No windows means no extra-shift availability. When disabled, the roster opt-in policy applies.</p>
    <ul className="space-y-2">{value.windows.map((w, i) => <li key={`${w.start}|${i}`} className="text-sm">
      {formatDateTime(w.start)} – {formatDateTime(w.end)}
      <button type="button" className="ml-2 underline" onClick={() => setDraft({ ...value, windows: value.windows.filter((_, n) => n !== i) })}>Remove window {i + 1}</button>
    </li>)}</ul>
    <label className="block text-sm">Available from<input className={field} type="datetime-local" ref={startInput} /></label>
    <label className="block text-sm">Available until<input className={field} type="datetime-local" ref={endInput} /></label>
    <button type="button" className={field} onClick={() => {
      const start = startInput.current?.value;
      const end = endInput.current?.value;
      if (!start || !end || new Date(end) <= new Date(start)) { setMessage("Choose an end after the start."); return; }
      if (value.windows.length >= 20) { setMessage("You can save up to 20 windows."); return; }
      setDraft({ enabled: true, windows: [...value.windows, { start: new Date(start).toISOString(), end: new Date(end).toISOString() }] });
      if (startInput.current) startInput.current.value = "";
      if (endInput.current) endInput.current.value = ""; setMessage("Window added. Save to update recommendations.");
    }}>Add availability window</button>
    <button type="button" className="min-h-11 w-full rounded-lg bg-primary text-primary-foreground" disabled={saving} onClick={async () => {
      setSaving(true); setMessage("");
      try {
        const saved = await apiRequest<Availability>("/api/offers/extra-availability", { method: "PUT", body: value, role: "physician", actorId: physicianId });
        setDraft(saved); refresh(); setMessage("Availability saved. Recommendations will re-check your windows.");
      } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save availability."); }
      finally { setSaving(false); }
    }}>{saving ? "Saving…" : "Save availability"}</button>
    <p className="text-xs text-muted-foreground">This does not book a shift. Credentials, rest, hours, approval and acceptance are still required. Existing accepted shifts remain commitments.</p>
    {message && <p role="status" className="text-sm">{message}</p>}
  </section>;
}
