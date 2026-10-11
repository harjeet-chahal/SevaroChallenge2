"use client";

import {
  Building2,
  Check,
  Clock,
  Hourglass,
  Loader2,
  MessageSquareText,
  Power,
  Timer,
  X,
} from "lucide-react";

import { TagBadge } from "@/components/shared/status-badges";
import { Button } from "@/components/ui/button";
import { Feedback } from "@/components/workflow/feedback";
import { useAction } from "@/components/workflow/use-action";
import { offersApi } from "@/lib/api/endpoints";
import type { OfferStatus, PhysicianOfferView } from "@/lib/api/types";
import { formatDateTime, formatDuration, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

function Field({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex gap-3">
      <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
      <div className="min-w-0">
        <dt className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          {label}
        </dt>
        <dd className="text-base font-medium break-words text-foreground">{children}</dd>
      </div>
    </div>
  );
}

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

  return (
    <article
      aria-label={`Shift offer ${offer.id}`}
      className={cn(
        "rounded-2xl border bg-card p-4 sm:p-5",
        offer.status !== "sent" && offer.status !== "accepted" && offer.status !== "active" && "opacity-80",
      )}
    >
      <header className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold whitespace-nowrap text-foreground">Split-shift offer</h3>
        <TagBadge tone={TONE[offer.status]}>{offer.status_label}</TagBadge>
      </header>

      <dl className="space-y-3">
        <Field icon={Building2} label={offer.hospitals.length > 1 ? "Hospitals" : "Hospital"}>
          {offer.hospitals.map((hospital) => hospital.name).join(", ")}
        </Field>
        <Field icon={Clock} label="Shift">
          {formatTime(offer.start_at, tz)} – {formatTime(offer.end_at, tz)}
          <span className="block text-sm font-normal text-muted-foreground">
            {formatDateTime(offer.start_at, tz)}
          </span>
        </Field>
        <Field icon={Hourglass} label="Total duration">
          {formatDuration(offer.duration_minutes)}
        </Field>
        <Field icon={Power} label="Time to come online">
          About {offer.minutes_to_online} min
          {offer.expected_online_at ? (
            <span className="block text-sm font-normal text-muted-foreground">
              {offer.activated_at
                ? `Online since ${formatTime(offer.activated_at, tz)}`
                : `Expected online ${formatTime(offer.expected_online_at, tz)}`}
            </span>
          ) : null}
        </Field>
        <Field icon={MessageSquareText} label="Why you were asked">
          <span className="text-base font-normal">{offer.reason}</span>
        </Field>
        <Field icon={Timer} label="Offer expires">
          {formatTime(offer.expires_at, tz)}
          {minutesLeft !== null ? (
            <span className="block text-sm font-normal text-warning-ink">
              {minutesLeft} simulated min left to reply
            </span>
          ) : null}
        </Field>
      </dl>

      {offer.message ? (
        <p className="mt-4 rounded-md border bg-muted/40 p-2 text-sm text-muted-foreground">
          {offer.message}
        </p>
      ) : null}

      <div className="mt-3">
        <Feedback feedback={feedback} />
      </div>

      {offer.can_accept || offer.can_decline ? (
        <div className="mt-4 grid grid-cols-2 gap-3">
          <Button
            variant="outline"
            size="lg"
            className="h-11 w-full text-base"
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
            className="h-11 w-full text-base"
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
          className="mt-4 h-11 w-full text-base"
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
