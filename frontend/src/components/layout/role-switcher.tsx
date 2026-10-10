"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { DEMO_ROLES, roleForPath } from "@/lib/roles";
import { cn } from "@/lib/utils";

/**
 * Demo-only navigation between role views. There is no login: this switches which
 * view you see. Permissions for workflow actions are enforced by the backend.
 */
export function RoleSwitcher({ className }: { className?: string }) {
  const pathname = usePathname();
  const active = roleForPath(pathname);
  const pending = useSystemStatus().config?.pending_approvals ?? 0;

  return (
    <nav aria-label="Demo role switcher" className={cn("flex items-center gap-2", className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            className="hidden shrink-0 items-center gap-1 rounded-md text-xs font-semibold tracking-wide text-navy-foreground/80 uppercase outline-none focus-visible:ring-2 focus-visible:ring-white/60 sm:inline-flex"
          >
            Demo role
            <Info className="size-3.5" aria-hidden />
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-64">
          Switch views without logging in. This is a demo convenience only; the backend
          enforces what each role may do.
        </TooltipContent>
      </Tooltip>
      <div className="grid w-full grid-cols-3 gap-1 rounded-lg bg-white/10 p-1 sm:w-auto">
        {DEMO_ROLES.map((role) => {
          const isActive = active?.id === role.id;
          const Icon = role.icon;
          return (
            <Link
              key={role.id}
              href={role.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-white/70 sm:text-sm",
                isActive
                  ? "bg-white text-navy shadow-sm"
                  : "text-navy-foreground/85 hover:bg-white/15 hover:text-navy-foreground",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span>{role.shortLabel}</span>
              {role.id === "clinical_lead" && pending > 0 ? (
                <span
                  className="rounded-full bg-warning px-1.5 text-[0.7rem] leading-4 font-semibold text-white"
                  aria-label={`${pending} pending approval${pending > 1 ? "s" : ""}`}
                >
                  {pending}
                </span>
              ) : null}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
