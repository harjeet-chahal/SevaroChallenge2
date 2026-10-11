"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { DEMO_ROLES, roleForPath } from "@/lib/roles";
import { cn } from "@/lib/utils";

/**
 * Demo-only navigation between role views, as pills. There is no login: this switches
 * which view you see. Permissions for workflow actions are enforced by the backend.
 */
export function RoleSwitcher({ className }: { className?: string }) {
  const pathname = usePathname();
  const active = roleForPath(pathname);
  const pending = useSystemStatus().config?.pending_approvals ?? 0;

  return (
    <nav
      aria-label="Demo role"
      title="Switch views without logging in. The backend enforces what each role may do."
      className={cn("flex items-center gap-1", className)}
    >
      {DEMO_ROLES.map((role) => {
        const isActive = active?.id === role.id;
        return (
          <Link
            key={role.id}
            href={role.href}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "inline-flex h-[34px] items-center gap-1.5 rounded-full border px-3.5 text-[13.5px] whitespace-nowrap",
              isActive
                ? "border-foreground bg-foreground font-semibold text-background"
                : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
            )}
          >
            <span className="min-[1180px]:hidden">{role.shortLabel}</span>
            <span className="max-[1179px]:hidden">{role.tabLabel}</span>
            {role.id === "clinical_lead" && pending > 0 ? (
              <span
                className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-warning px-1 font-mono text-micro font-semibold text-warning-foreground"
                aria-label={`${pending} pending approval${pending > 1 ? "s" : ""}`}
              >
                {pending}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
