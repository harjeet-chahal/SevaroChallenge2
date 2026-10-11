"use client";

import { createContext, useContext } from "react";

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
          <p className="text-caption text-muted-foreground">{info}</p>
        ) : null}
        <div className={contentClassName}>{children}</div>
      </section>
    );
  }

  return (
    <section aria-labelledby={headingId} id={id} className={cn("flex scroll-mt-24", className)}>
      <div className="flex w-full min-w-0 flex-col rounded-xl bg-card-subtle ring-1 ring-border">
        <div className="flex items-start gap-3 border-b border-border-subtle px-[18px] py-4">
          <div className="min-w-0 flex-1 space-y-0.5">
            <div className="flex items-center gap-2">
              {Icon ? <Icon className="size-4 shrink-0 text-primary" aria-hidden /> : null}
              <h2 id={headingId} className="text-base leading-snug font-semibold">
                {title}
              </h2>
              {info ? <InfoTip label={`About ${title.toLowerCase()}`}>{info}</InfoTip> : null}
            </div>
            {description ? (
              <p className="text-caption text-muted-foreground">{description}</p>
            ) : null}
          </div>
          {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
        </div>
        <div className={cn("flex-1 px-[18px] py-4", contentClassName)}>{children}</div>
      </div>
    </section>
  );
}
