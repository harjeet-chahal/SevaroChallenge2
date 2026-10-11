"use client";

import { createContext, useContext } from "react";

import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { InfoTip } from "./info-tip";

/**
 * Inside a tab panel the tab already names the section, so sections render "bare": no
 * card chrome or repeated title, just their action row and content.
 */
const BareSectionContext = createContext(false);

export function BareSections({ children }: { children: React.ReactNode }) {
  return <BareSectionContext value>{children}</BareSectionContext>;
}

export function SectionCard({
  title,
  description,
  info,
  icon: Icon,
  action,
  children,
  className,
  contentClassName,
  id,
}: {
  title: string;
  /** One short line under the title. Keep method notes in ``info``. */
  description?: string;
  /** How it works / why: shown on demand behind an (i) next to the title. */
  info?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
  id?: string;
}) {
  const bare = useContext(BareSectionContext);
  const headingId = `section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  if (bare) {
    return (
      <section aria-label={title} id={id} className={cn("space-y-3", className)}>
        {action ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {info ? <InfoTip label={`About ${title.toLowerCase()}`}>{info}</InfoTip> : null}
            {action}
          </div>
        ) : info ? (
          <p className="text-xs text-muted-foreground">{info}</p>
        ) : null}
        <div className={contentClassName}>{children}</div>
      </section>
    );
  }

  return (
    <section aria-labelledby={headingId} id={id} className={cn("flex scroll-mt-24", className)}>
      <Card className="w-full min-w-0 shadow-xs">
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2 font-semibold">
            {Icon ? <Icon className="size-4 text-primary" aria-hidden /> : null}
            <h2 id={headingId}>{title}</h2>
            {info ? <InfoTip label={`About ${title.toLowerCase()}`}>{info}</InfoTip> : null}
          </CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
          {action ? <CardAction>{action}</CardAction> : null}
        </CardHeader>
        <CardContent className={cn("flex-1", contentClassName)}>{children}</CardContent>
      </Card>
    </section>
  );
}
