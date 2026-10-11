import { cn } from "@/lib/utils";

/** Eyebrow / overline: small caps above a title or inside a panel. */
export const EYEBROW = "text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  /** Extra line under the description (e.g. the dataset chip). */
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-x-6 gap-y-4", className)}>
      <div className="min-w-0 space-y-2">
        {eyebrow ? <p className={EYEBROW}>{eyebrow}</p> : null}
        <h1 className="font-serif text-[34px] leading-[1.05] font-normal tracking-[-0.01em] text-foreground sm:text-[40px]">
          {title}
        </h1>
        {description ? (
          <p className="max-w-[760px] text-body text-pretty text-foreground-2">{description}</p>
        ) : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-end gap-2">{actions}</div> : null}
    </div>
  );
}
