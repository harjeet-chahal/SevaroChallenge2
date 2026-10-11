"use client";

import {
  Clock4,
  FileUp,
  FlaskConical,
  LayoutDashboard,
  Network,
  ScrollText,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/coordinator", label: "Command Center", icon: LayoutDashboard },
  { href: "/time-machine", label: "Time Machine", icon: Clock4 },
  { href: "/network", label: "Network", icon: Network },
  { href: "/simulator", label: "Rescue Simulator", icon: Workflow },
  { href: "/contracts", label: "Rescue Contracts", icon: ScrollText },
  { href: "/chaos", label: "Chaos Lab", icon: FlaskConical },
  { href: "/import", label: "Data Import", icon: FileUp },
] as const;

/** Operations navigation (coordinator views). Hidden on the role-specific phone/lead views. */
export function OpsNav() {
  const pathname = usePathname();
  if (pathname === "/" || pathname.startsWith("/physician") || pathname.startsWith("/clinical-lead")) {
    return null;
  }
  return (
    <nav aria-label="Operations views" className="border-b border-white/10 bg-navy/95">
      <div className="mx-auto flex max-w-screen-2xl gap-1 overflow-x-auto px-4 py-1.5 sm:px-6 lg:px-8">
        {ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-primary",
                active
                  ? "bg-primary/15 text-primary"
                  : "text-navy-foreground/75 hover:bg-white/5 hover:text-navy-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
