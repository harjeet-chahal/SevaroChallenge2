import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function SectionCard({
  title,
  description,
  icon: Icon,
  action,
  children,
  className,
  contentClassName,
}: {
  title: string;
  description?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const headingId = `section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;

  return (
    <section aria-labelledby={headingId} className={cn("flex", className)}>
      <Card className="w-full min-w-0 gap-0 py-0">
        <CardHeader className="border-b border-border-subtle px-[18px] py-4">
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            {Icon ? <Icon className="size-4 text-primary" aria-hidden /> : null}
            <h2 id={headingId}>{title}</h2>
          </CardTitle>
          {description ? (
            <CardDescription className="text-caption leading-snug text-muted-foreground">{description}</CardDescription>
          ) : null}
          {action ? <CardAction>{action}</CardAction> : null}
        </CardHeader>
        <CardContent className={cn("flex-1 px-[18px] py-4", contentClassName)}>{children}</CardContent>
      </Card>
    </section>
  );
}
