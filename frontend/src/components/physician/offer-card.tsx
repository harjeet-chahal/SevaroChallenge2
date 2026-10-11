"use client";

import { Check, CircleCheck, Loader2, Power, X } from "lucide-react";

import { TagBadge } from "@/components/shared/status-badges";
import { Button } from "@/components/ui/button";
import { Feedback } from "@/components/workflow/feedback";
import { useAction } from "@/components/workflow/use-action";
import { offersApi } from "@/lib/api/endpoints";
import type { OfferStatus, PhysicianOfferView } from "@/lib/api/types";
import { formatDay, formatDuration, formatHm, zoneAbbr } from "@/lib/format";
import { cn } from "@/lib/utils";

const TONE: Record<OfferStatus, "warning" | "info" | "success" | "neutral"> = {
  sent: "warning",
  accepted: "info",
  active: "success",
  completed: "success",
  declined: "neutral",
  expired: "neutral",
  withdrawn: "neutral",
  redundant: "neutral",
  cancelled: "neutral",
};

/**
 * A split-shift offer as the physician sees it: hospitals, hours, time to come online,
 * why they were asked and the deadline. No patient information is ever included.
 */
export function OfferCard({
  offer,
  physicianId,
  simulationTime,
}: {
  offer: PhysicianOfferView;
  physicianId: string;
  simulationTime: string | null;
}) {
  const { pending, feedback, run } = useAction();
  const tz = offer.hospital_timezone;
  const minutesLeft =
    simulationTime && offer.status === "sent"
      ? Math.max(
          0,
          Math.round((new Date(offer.expires_at).getTime() - new Date(simulationTime).getTime()) / 60000),
        )
      : null;

  const hm = (iso: string) => formatHm(iso, tz);
  const zone = zoneAbbr(offer.start_at, tz);
  const onlineBy = offer.expected_online_at ? hm(offer.expected_online_at) : null;

  return (
    <article
      aria-label={`Shift offer ${offer.id}`}
      className={cn(
        "flex flex-col gap-4 rounded-[18px] border bg-card p-5",
        offer.status === "accepted" && "border-success-border",
        offer.status !== "sent" && offer.status !== "accepted" && offer.status !== "active" && "border-dashed opacity-80",
      )}
    >
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold tracking-[0.1em] whitespace-nowrap text-muted-foreground uppercase">
          Split-shift offer
        </h3>
        <TagBadge tone={TONE[offer.status]}>{offer.status_label}</TagBadge>
      </header>

      <div className="flex flex-col gap-1">
        <span className="text-[22px] leading-tight font-semibold">
          {offer.hospitals.map((hospital) => hospital.name).join(", ")}
        </span>
        <span className="font-mono text-[17px] text-foreground-2 tabular-nums">
          {hm(offer.start_at)} – {hm(offer.end_at)} {zone}
        </span>
        <span className="text-caption text-muted-foreground">
          {formatDay(offer.start_at, tz)} · {formatDuration(offer.duration_minutes)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2.5">
        <div className="flex flex-col gap-1 rounded-xl bg-inset p-3">
          <span className="text-label text-muted-foreground">
            {offer.activated_at ? "Online since" : "Come online by"}
          </span>
          <span className="font-mono text-xl font-semibold tabular-nums">
            {offer.activated_at ? hm(offer.activated_at) : (onlineBy ?? `~${offer.minutes_to_online} min`)}
          </span>
          <span className="text-label text-muted-foreground">about {offer.minutes_to_online} min to sign in</span>
        </div>
        <div className="flex flex-col gap-1 rounded-xl bg-inset p-3">
          <span className="text-label text-muted-foreground">Reply within</span>
          <span
            className={cn(
              "font-mono text-xl font-semibold tabular-nums",
              minutesLeft !== null && minutesLeft < 2 && "text-warning-ink",
            )}
          >
            {minutesLeft !== null ? `${minutesLeft} min` : "—"}
          </span>
          <span className="text-label text-muted-foreground">expires {hm(offer.expires_at)} · sim clock</span>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">Why you were asked</span>
        <span className="text-[14.5px] leading-normal">{offer.reason}</span>
      </div>

      {offer.status === "accepted" ? (
        <div className="flex flex-col gap-1.5 rounded-xl border border-success-border bg-success-soft p-3.5">
          <span className="flex items-center gap-1.5 text-base font-semibold text-success-ink">
            <CircleCheck className="size-4" aria-hidden />
            You&apos;re confirmed{onlineBy ? ` — come online by ${onlineBy}` : ""}
          </span>
          <span className="text-[13px] leading-snug text-foreground-2">
            Accepted is not online yet. Your shift becomes active when you sign in.
          </span>
        </div>
      ) : null}

      {offer.message ? (
        <p className="rounded-xl bg-raised p-3 text-sm text-foreground-2">{offer.message}</p>
      ) : null}

      <Feedback feedback={feedback} />

      {offer.can_accept || offer.can_decline ? (
        <div className="grid grid-cols-2 gap-2.5">
          <Button
            variant="outline"
            size="lg"
            className="h-14 w-full rounded-[14px] text-base active:scale-[.98]"
            disabled={!offer.can_decline || pending !== null}
            onClick={() =>
              run("decline", async () => {
                const result = await offersApi.respond(offer.id, physicianId, "decline");
                return result.message;
              })
            }
          >
            {pending === "decline" ? <Loader2 className="animate-spin" aria-hidden /> : <X aria-hidden />}
            Decline
          </Button>
          <Button
            size="lg"
            className="h-14 w-full rounded-[14px] text-base active:scale-[.98]"
            disabled={!offer.can_accept || pending !== null}
            onClick={() =>
              run("accept", async () => {
                const result = await offersApi.respond(offer.id, physicianId, "accept");
                return result.message;
              })
            }
          >
            {pending === "accept" ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
            Accept
          </Button>
        </div>
      ) : null}

      {offer.can_go_online ? (
        <Button
          size="lg"
          className="h-14 w-full rounded-[14px] text-base"
          disabled={pending !== null}
          onClick={() =>
            run("online", async () => {
              await offersApi.activate(offer.id, "physician", physicianId);
              return "You are online. Calls reach you only from the hospitals listed.";
            })
          }
        >
          {pending === "online" ? <Loader2 className="animate-spin" aria-hidden /> : <Power aria-hidden />}
          I’m online — start my shift
        </Button>
      ) : null}
    </article>
  );
}
