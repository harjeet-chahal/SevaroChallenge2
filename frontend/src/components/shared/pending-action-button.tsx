"use client";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * A visibly present but disabled action, with a tooltip explaining why.
 * Disabled buttons swallow pointer events, so the tooltip is anchored on a focusable wrapper.
 */
export function PendingActionButton({
  label,
  icon: Icon,
  reason = "Available once the workflow API is implemented.",
  variant = "outline",
  size = "default",
  className,
  wrapperClassName,
}: {
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  reason?: string;
  variant?: React.ComponentProps<typeof Button>["variant"];
  size?: React.ComponentProps<typeof Button>["size"];
  className?: string;
  wrapperClassName?: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          role="button"
          aria-disabled="true"
          aria-label={`${label} — unavailable. ${reason}`}
          className={cn(
            "inline-flex rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            wrapperClassName,
          )}
        >
          <Button
            variant={variant}
            size={size}
            disabled
            tabIndex={-1}
            aria-hidden
            className={className}
          >
            {Icon ? <Icon aria-hidden /> : null}
            {label}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}
