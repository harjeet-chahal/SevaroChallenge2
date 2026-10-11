"use client";

import { useCallback, useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { ApiError, NetworkError } from "@/lib/api/client";
import type { Intervention } from "@/lib/api/types";

export interface ActionFeedback {
  /** "warning": the action went through, but not entirely as planned. */
  tone: "success" | "warning" | "error";
  message: string;
  items: string[];
}

/**
 * What "Send offers" actually did. The backend may skip a planned offer that fails its
 * re-check at send time; it still succeeds and records the skip only in the audit trail,
 * so compare the plan with the offers that exist instead of reporting plain success.
 */
export function sentOffersFeedback(sent: Intervention, note: string): ActionFeedback {
  const count = sent.offers.filter((o) => o.status === "sent").length;
  const reached = new Set(sent.offers.map((o) => o.physician_id));
  const missed = sent.offer_plan.filter((p) => !reached.has(p.physician_id));
  if (!missed.length) {
    return { tone: "success", message: `Sent ${count} offer(s) ${note}`, items: [] };
  }
  return {
    tone: "warning",
    message: `Sent ${count} of ${sent.offer_plan.length} planned offers ${note}`,
    items: [
      ...missed.map((p) => `Not sent: ${p.display_name} — see the audit trail for why.`),
      ...(sent.status_reason ? [sent.status_reason] : []),
    ],
  };
}

/** Server-side reasons carried in the error envelope (blocking reasons, problems, ...). */
function errorItems(details: unknown): string[] {
  if (!details || typeof details !== "object") return [];
  const d = details as Record<string, unknown>;
  const lists = [d.blocking_reasons, d.problems, d.revalidation];
  return lists.flatMap((l) => (Array.isArray(l) ? l.filter((x) => typeof x === "string") : []));
}

/**
 * Runs one workflow mutation at a time and reports exactly what the server said. After
 * every call (success or not) the shared status is refreshed so all views refetch.
 */
export function useAction() {
  const { refresh } = useSystemStatus();
  const [pending, setPending] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<ActionFeedback | null>(null);

  const run = useCallback(
    async (key: string, action: () => Promise<string | ActionFeedback | void>) => {
      setPending(key);
      setFeedback(null);
      try {
        const result = await action();
        if (typeof result === "string") {
          setFeedback({ tone: "success", message: result, items: [] });
        } else if (result) {
          setFeedback(result);
        }
        return true;
      } catch (error) {
        if (error instanceof ApiError) {
          setFeedback({ tone: "error", message: error.message, items: errorItems(error.details) });
        } else if (error instanceof NetworkError) {
          setFeedback({ tone: "error", message: error.message, items: [] });
        } else {
          setFeedback({ tone: "error", message: "Unexpected error", items: [] });
        }
        return false;
      } finally {
        setPending(null);
        refresh();
      }
    },
    [refresh],
  );

  return { pending, feedback, run, clear: () => setFeedback(null) };
}
