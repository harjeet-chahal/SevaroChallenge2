import { CircleCheck, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

import type { ActionFeedback } from "./use-action";

/** The server's answer to the last action, in plain words. Never optimistic. */
export function Feedback({ feedback }: { feedback: ActionFeedback | null }) {
  if (!feedback) return null;
  const error = feedback.tone === "error";
  const Icon = error ? TriangleAlert : CircleCheck;
  return (
    <div
      role={error ? "alert" : "status"}
      className={cn(
        "flex gap-2 rounded-md border p-2.5 text-sm",
        error
          ? "border-critical-border bg-critical-soft text-critical-ink"
          : "border-success-border bg-success-soft text-success-ink",
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="font-medium">{feedback.message}</p>
        {feedback.items.length ? (
          <ul className="list-disc space-y-0.5 pl-4 text-xs">
            {feedback.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
