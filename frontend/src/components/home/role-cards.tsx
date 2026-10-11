"use client";

import Link from "next/link";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useLiveResource } from "@/hooks/use-live-resource";
import { workflowApi } from "@/lib/api/endpoints";
import { neurogridApi } from "@/lib/api/neurogrid";
import { formatHm } from "@/lib/format";
import { cn } from "@/lib/utils";

import { fmtMin } from "@/components/neurogrid/kit";

/** Cursor-following spotlight: the card's background reads --mx / --my. */
function spot(e: React.MouseEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
  e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
}

const TONE = {
  primary: "[--tone:var(--primary)]",
  warning: "[--tone:var(--warning)]",
  info: "[--tone:var(--info)]",
} as const;

function RoleCard({
  href,
  tone,
  title,
  description,
  meta,
  children,
}: {
  href: string;
  tone: keyof typeof TONE;
  title: string;
  description: string;
  meta: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      onMouseMove={spot}
      className={cn(
        TONE[tone],
        "flex flex-col gap-[18px] rounded-3xl border border-border-subtle p-[26px] transition-[transform,border-color] duration-250 hover:-translate-y-[3px] hover:border-[color-mix(in_oklch,var(--tone)_55%,transparent)]",
        "bg-[radial-gradient(420px_circle_at_var(--mx,50%)_var(--my,0%),color-mix(in_oklch,var(--tone)_11%,transparent),transparent_65%),var(--card)]",
      )}
    >
      {children}
      <span className="flex flex-col gap-1.5">
        <span className="text-xl font-semibold">{title}</span>
        <span className="text-sm leading-relaxed text-foreground-2">{description}</span>
      </span>
      <span className="mt-auto flex items-center justify-between text-[13px] text-muted-foreground">
        <span>{meta}</span>
        <span className="font-semibold text-primary-ink">Open →</span>
      </span>
    </Link>
  );
}

function CoordinatorPreview() {
  const lsm = useLiveResource((s) => neurogridApi.lastSafeMoment(s));
  const item = lsm.data?.items.find((i) => i.latest_initiation_at) ?? lsm.data?.items[0];
  const rem = item?.remaining_minutes ?? null;
  const frac = item && rem !== null ? Math.min(1, Math.max(0, rem / Math.max(item.minutes_until_shortfall, 1))) : 0;
  return (
    <div className="flex flex-col gap-2.5 rounded-2xl bg-clock-bg p-4 text-clock-fg">
      <div className="flex justify-between gap-2 text-label opacity-70">
        <span className="truncate">Last safe moment{item ? ` · ${item.hospital_name}` : ""}</span>
        <span>projected</span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[30px] font-medium tracking-[-0.03em] tabular-nums">
          {item ? (rem === null ? "—" : fmtMin(rem)) : lsm.data ? "none" : "…"}
        </span>
        <span className="text-xs opacity-70">
          {item?.latest_initiation_at ? `to start rescue · by ${formatHm(item.latest_initiation_at, item.timezone)}` : "to start rescue"}
        </span>
      </div>
      <div className="h-1 overflow-hidden rounded-sm bg-clock-fg/15">
        <div className="h-full bg-primary transition-[width] duration-700" style={{ width: `${frac * 100}%` }} />
      </div>
    </div>
  );
}

function LeadPreview() {
  const { config } = useSystemStatus();
  const list = useLiveResource((s) => workflowApi.list("clinical_lead", s));
  const pending = (list.data?.items ?? []).filter((i) => i.status === "pending_approval").slice(0, 2);
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border-subtle bg-card-subtle p-3.5">
      <div className="flex justify-between text-label text-muted-foreground">
        <span>Pending approvals</span>
        <span className="rounded-full bg-warning px-[7px] font-mono font-semibold text-warning-foreground">
          {config?.pending_approvals ?? 0}
        </span>
      </div>
      {pending.length ? (
        pending.map((i) => (
          <div key={i.id} className="flex items-center justify-between gap-2 rounded-[10px] bg-card px-2.5 py-[9px] text-[13px]">
            <span className="truncate">{i.title}</span>
            <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-label font-semibold text-primary-foreground">
              Review
            </span>
          </div>
        ))
      ) : (
        <div className="rounded-[10px] bg-card px-2.5 py-[9px] text-[13px] text-muted-foreground">
          Nothing waiting — proposals appear here first.
        </div>
      )}
    </div>
  );
}

function PhysicianPreview() {
  return (
    <div className="flex h-[132px] justify-center overflow-hidden rounded-2xl border border-border-subtle bg-card-subtle pt-3">
      <div className="flex w-[190px] flex-col gap-2 rounded-t-[18px] border border-b-0 bg-card p-3">
        <div className="flex justify-between text-[11px] text-muted-foreground">
          <span>Shift offer</span>
          <span className="font-mono">10 min to reply</span>
        </div>
        <span className="text-sm font-semibold">Hospitals · hours · reason</span>
        <div className="grid grid-cols-2 gap-1.5 text-xs">
          <span className="grid h-[30px] place-items-center rounded-[9px] border border-border-strong">Decline</span>
          <span className="grid h-[30px] place-items-center rounded-[9px] bg-primary font-semibold text-primary-foreground">
            Accept
          </span>
        </div>
      </div>
    </div>
  );
}

export function RoleCards() {
  return (
    <section aria-labelledby="seat-heading" className="flex flex-col gap-[18px]">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="seat-heading" className="font-serif text-[34px] font-normal tracking-[-0.01em]">
          Choose your seat
        </h2>
        <span className="text-[13.5px] text-muted-foreground">No login in this demo. Each role sees only what it needs.</span>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,300px),1fr))] gap-4">
        <RoleCard
          href="/coordinator"
          tone="primary"
          title="Operations coordinator"
          description="Watch the network, find the most urgent problem, forecast the last safe moment and propose rescues."
          meta="Desktop · 7 views"
        >
          <CoordinatorPreview />
        </RoleCard>
        <RoleCard
          href="/clinical-lead"
          tone="warning"
          title="Clinical lead"
          description="Approve or reject proposed rescues. Nothing reaches a physician without this approval."
          meta="Desktop · re-validated on approval"
        >
          <LeadPreview />
        </RoleCard>
        <RoleCard
          href="/physician"
          tone="info"
          title="Off-shift physician"
          description="Receive shift offers on your phone and accept or decline them. Offers never include patient information."
          meta="Mobile · 390 px"
        >
          <PhysicianPreview />
        </RoleCard>
      </div>
    </section>
  );
}
