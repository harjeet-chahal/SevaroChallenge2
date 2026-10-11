"use client";

import { Send } from "lucide-react";

import { InfoTip } from "@/components/shared/info-tip";
import { RankMovement, TagBadge, VoluntaryBadge } from "@/components/shared/status-badges";
import { Button } from "@/components/ui/button";
import type { NeedRanking, RankedCandidate } from "@/lib/api/types";
import { formatMoney, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Bullets, Disclosure } from "./shared";

function Facts({ e, tz }: { e: RankedCandidate; tz?: string | null }) {
  if (!e.offer) return null;
  return (
    <p className="text-xs text-muted-foreground font-mono tabular-nums">
      {formatTime(e.offer.start_at, tz)}–{formatTime(e.offer.end_at, tz)} · online{" "}
      {formatTime(e.offer.online_at, tz)} · removes {e.coverage_physician_minutes} physician-min
      {e.coverage_share_of_best !== null && e.coverage_share_of_best < 1
        ? ` (${Math.round(e.coverage_share_of_best * 100)}% of best)`
        : ""}
      {e.cost ? ` · est. ${formatMoney(e.cost.amount, e.cost.currency)}` : ""}
      {e.hours_worked_trailing_7d !== null ? ` · ${e.hours_worked_trailing_7d} h in 7 d` : ""}
    </p>
  );
}

function Row({
  e,
  tz,
  compact,
  onPropose,
}: {
  e: RankedCandidate;
  tz?: string | null;
  compact: boolean;
  onPropose?: (e: RankedCandidate) => void;
}) {
  const moved = e.movement > 0;
  return (
    <li
      className={cn(
        "flex gap-3 rounded-lg border p-2.5",
        e.voluntary_preference_applied ? "border-success-border bg-success-soft/40" : "bg-card",
      )}
    >
      <span
        aria-label={`Rank ${e.rank}`}
        className={cn(
          "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold font-mono tabular-nums",
          e.rank === 1 ? "bg-primary text-primary-foreground" : "bg-muted text-foreground",
        )}
      >
        {e.rank}
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-semibold text-foreground">{e.display_name}</span>
          <VoluntaryBadge match={e.voluntary} />
          <RankMovement movement={e.movement} from={e.rank_without_voluntary} />
          {e.in_plan && !compact ? <TagBadge tone="info">In recommended plan</TagBadge> : null}
        </div>
        <Facts e={e} tz={tz} />
        {moved && compact ? (
          <p className="text-xs text-success-ink">{e.reasons[0]}</p>
        ) : null}
        {!compact ? (
          <Disclosure summary={moved ? "Why it moved up" : "Why this rank"}>
            <Bullets items={e.reasons} className="text-xs" />
          </Disclosure>
        ) : null}
      </div>
      {onPropose && !compact ? (
        <Button size="sm" variant={e.rank === 1 ? "default" : "outline"} onClick={() => onPropose(e)}>
          <Send aria-hidden />
          Propose
        </Button>
      ) : null}
    </li>
  );
}

/**
 * Who to ask first for one coverage need, ranked by the backend. Volunteers are
 * highlighted only when their availability actually counts; the reasons (including why a
 * physician moved) are one click away.
 */
export function RankedPhysicians({
  ranking,
  tz,
  compact = false,
  limit,
  onPropose,
  title,
}: {
  ranking: NeedRanking;
  tz?: string | null;
  compact?: boolean;
  limit?: number;
  onPropose?: (e: RankedCandidate) => void;
  title?: string;
}) {
  const ranked = ranking.entries.filter((e) => e.rank !== null);
  const shown = limit ? ranked.slice(0, limit) : ranked;
  const unranked = ranking.entries.filter((e) => e.rank === null);
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        <h3 className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          {title ?? `Who to ask first — ${ranking.hospital_names.join(", ")}`}
        </h3>
        <InfoTip label="How physicians are ranked">
          <span className="block space-y-1">
            {ranking.method.map((m) => (
              <span key={m} className="block">
                {m}
              </span>
            ))}
          </span>
        </InfoTip>
      </div>
      {ranking.shortage_start && !compact ? (
        <p className="text-xs text-muted-foreground">
          Shortage {formatTime(ranking.shortage_start, tz)}–
          {ranking.shortage_end ? formatTime(ranking.shortage_end, tz) : "…"} (planning window)
        </p>
      ) : null}
      {shown.length ? (
        <ol className="space-y-1.5" aria-label="Ranked physicians">
          {shown.map((e) => (
            <Row key={e.physician_id} e={e} tz={tz} compact={compact} onPropose={onPropose} />
          ))}
        </ol>
      ) : (
        <p className="text-xs text-muted-foreground">
          Nobody can be asked under the split-shift rules for this need.
        </p>
      )}
      {!compact && unranked.length ? (
        <Disclosure summary={`Cannot be asked (${unranked.length})`}>
          <ul className="space-y-1 text-xs">
            {unranked.map((e) => (
              <li key={e.physician_id} className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium">{e.display_name}</span>
                <VoluntaryBadge match={e.voluntary} />
                <span className="basis-full text-muted-foreground">{e.summary}</span>
              </li>
            ))}
          </ul>
        </Disclosure>
      ) : null}
    </div>
  );
}
