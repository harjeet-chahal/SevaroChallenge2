"use client";

import { useCallback, useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { ApiError, NetworkError } from "@/lib/api/client";

export interface ActionFeedback {
  tone: "success" | "error";
  message: string;
  items: string[];
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
    async (key: string, action: () => Promise<string | void>) => {
      setPending(key);
      setFeedback(null);
      try {
        const message = await action();
        if (message) setFeedback({ tone: "success", message, items: [] });
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
