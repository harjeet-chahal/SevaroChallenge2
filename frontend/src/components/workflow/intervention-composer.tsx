"use client";

import { FilePlus2, Loader2, RefreshCw, Send, X } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionCard } from "@/components/shared/section-card";
import { TagBadge } from "@/components/shared/status-badges";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { workflowApi } from "@/lib/api/endpoints";
import type { InterventionCreate } from "@/lib/api/types";
import { INTERVENTION_TYPE_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { Feedback } from "./feedback";
import { InterventionDetailView } from "./intervention-detail";
import { useAction } from "./use-action";
import { useWorkflow } from "./workflow-provider";

/**
 * The coordinator's proposal. The backend builds and validates it (a dry run at the
 * current data version), and re-validates again on submit. Submitting a split shift only
 * creates a pending clinical-lead approval: no physician is contacted.
 */
export function InterventionComposer({ className }: { className?: string }) {
  const { composer, closeComposer, select } = useWorkflow();
  const { config } = useSystemStatus();
  // Backups chosen for this proposal, anchored to the primary the server picked first, so
  // adding a backup never changes who the primary physician is.
  const [backups, setBackups] = useState<{ nonce: number; ids: string[]; primary: string | null }>(
    { nonce: 0, ids: [], primary: null },
  );
  const [note, setNote] = useState("");
  const { pending, feedback, run } = useAction();

  const current = composer && backups.nonce === composer.nonce ? backups : null;
  const backupIds = current?.ids ?? [];
  const anchoredPrimary = composer?.physicianIds?.[0] ?? current?.primary ?? null;
  const body: InterventionCreate | null = composer
    ? {
        type: composer.type,
        alert_id: composer.alertId ?? null,
        physician_ids:
          composer.type === "split_shift" && anchoredPrimary
            ? [anchoredPrimary, ...backupIds.filter((id) => id !== anchoredPrimary)]
            : undefined,
        hospital_ids: composer.hospitalIds,
        consult_id: composer.consultId ?? null,
      }
    : null;
  // Re-run the dry run whenever the data, workflow state or clock changes (revalidation).
  const key =
    composer && config?.dataset_loaded
      ? `${composer.nonce}|${backupIds.join(",")}|${config.data_version}|${config.workflow_version}|${config.simulation_time}`
      : null;
  const preview = useKeyedResource(key, (signal) => workflowApi.preview(body!, signal));
  const data = preview.data;
  const draft = data?.intervention ?? null;

  const primary = draft?.offer_plan.find((p) => p.role === "primary")?.physician_id;
  const backupChoices =
    draft?.type === "split_shift"
      ? draft.candidates.filter(
          (c) =>
            c.eligible &&
            c.physician_id !== primary &&
            c.gap_hospital_ids.some((h) => draft.problem.hospital_ids.includes(h)),
        )
      : [];

  if (!composer) {
    return (
      <SectionCard
        className={className}
        title="Intervention proposal"
        icon={FilePlus2}
        description="Choose an action on an alert or a split-shift recommendation to prepare a proposal."
      >
        <div className="space-y-3">
          <Feedback feedback={feedback} />
          <EmptyState
            compact
            icon={FilePlus2}
            title="Nothing being prepared"
            description="Use “Propose split shift”, “Request escalation” or “Propose reassignment” in the alert details, or “Propose” on a split-shift recommendation."
          />
        </div>
      </SectionCard>
    );
  }

  const submitLabel =
    composer.type === "reassign_consult"
      ? "Save reassignment proposal"
      : "Submit for clinical-lead approval";

  return (
    <section id="intervention-composer" className={cn("scroll-mt-24", className)}>
      <SectionCard
        title={`Proposal: ${INTERVENTION_TYPE_LABELS[composer.type]}`}
        icon={FilePlus2}
        description="Built and validated by the backend against the current data. Nothing is sent from here."
        action={
          <Button variant="ghost" size="sm" onClick={closeComposer} aria-label="Close proposal">
            <X aria-hidden />
            Close
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {preview.loading ? (
              <span className="inline-flex items-center gap-1">
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
                Validating against the current data…
              </span>
            ) : data ? (
              <TagBadge tone={data.valid ? "success" : "critical"}>
                {data.valid ? "Valid now" : "Not valid now"} · data version {data.data_version}
              </TagBadge>
            ) : null}
            <Button variant="ghost" size="xs" onClick={preview.reload}>
              <RefreshCw aria-hidden />
              Re-check
            </Button>
          </div>

          {preview.error ? (
            <p className="text-sm text-critical" role="alert">
              {preview.error}
            </p>
          ) : null}

          {data && (data.blocking_reasons.length || data.warnings.length) ? (
            <div className="space-y-1 text-sm">
              {data.blocking_reasons.map((r) => (
                <p key={r} className="rounded-md border border-critical-border bg-critical-soft p-2 text-critical">
                  {r}
                </p>
              ))}
              {data.warnings.map((w) => (
                <p key={w} className="rounded-md border border-warning-border bg-warning-soft p-2 text-warning">
                  {w}
                </p>
              ))}
            </div>
          ) : null}

          {draft ? <InterventionDetailView intervention={draft} /> : null}

          {backupChoices.length ? (
            <fieldset className="space-y-1 rounded-lg border p-3 text-sm">
              <legend className="px-1 text-xs font-semibold text-muted-foreground uppercase">
                Backup offers (optional)
              </legend>
              <p className="text-xs text-muted-foreground">
                Sent together with the primary offer after approval. The first binding acceptance
                fills the need; the others are withdrawn automatically.
              </p>
              {backupChoices.map((c) => (
                <label key={c.physician_id} className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={backupIds.includes(c.physician_id)}
                    onChange={(e) =>
                      setBackups({
                        nonce: composer.nonce,
                        primary: anchoredPrimary ?? primary ?? null,
                        ids: e.target.checked
                          ? [...backupIds, c.physician_id]
                          : backupIds.filter((id) => id !== c.physician_id),
                      })
                    }
                  />
                  <span>
                    <span className="font-medium">{c.display_name}</span>{" "}
                    <span className="text-xs text-muted-foreground">{c.summary}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}

          <div className="space-y-1">
            <label htmlFor="proposal-note" className="text-xs font-semibold text-muted-foreground uppercase">
              Coordinator note (internal — never sent to physicians)
            </label>
            <Textarea
              id="proposal-note"
              value={note}
              maxLength={2000}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Optional context for the clinical lead"
            />
          </div>

          <Feedback feedback={feedback} />

          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="outline" onClick={closeComposer}>
              Discard
            </Button>
            <Button
              disabled={!data?.valid || preview.loading || pending !== null}
              onClick={() =>
                run("propose", async () => {
                  const created = await workflowApi.propose({
                    ...body!,
                    rationale: note || null,
                    expected_data_version: data?.data_version ?? null,
                  });
                  select(created.id);
                  closeComposer();
                  setNote("");
                  document
                    .getElementById("intervention-board")
                    ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  return created.status === "pending_approval"
                    ? `${created.id} created — waiting for clinical-lead approval. No physician has been contacted.`
                    : `${created.id} created (${created.status}).`;
                })
              }
            >
              {pending === "propose" ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
              {submitLabel}
            </Button>
          </div>
        </div>
      </SectionCard>
    </section>
  );
}
