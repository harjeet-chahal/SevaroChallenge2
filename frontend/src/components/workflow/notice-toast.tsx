"use client";

import { CheckCheck, X } from "lucide-react";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";

import { useWorkflow } from "./workflow-provider";

const DISMISS_AFTER_MS = 10_000;

/**
 * Confirms a submitted proposal without moving the coordinator away from the alert they
 * were triaging; "View" jumps to the intervention when they want it.
 */
export function WorkflowNoticeToast() {
  const { notice, setNotice } = useWorkflow();

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, [notice, setNotice]);

  if (!notice) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed right-4 bottom-4 z-50 flex w-[min(28rem,calc(100vw-2rem))] items-start gap-2.5 rounded-lg border border-success-border bg-card p-3 text-sm shadow-lg animate-in fade-in-0 slide-in-from-bottom-2"
    >
      <CheckCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-medium">{notice}</p>
        <Button
          variant="link"
          size="xs"
          className="h-auto px-0"
          onClick={() => {
            setNotice(null);
            document
              .getElementById("intervention-board")
              ?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        >
          View in Interventions
        </Button>
      </div>
      <Button
        variant="ghost"
        size="icon-xs"
        aria-label="Dismiss"
        className="text-muted-foreground"
        onClick={() => setNotice(null)}
      >
        <X aria-hidden />
      </Button>
    </div>
  );
}
