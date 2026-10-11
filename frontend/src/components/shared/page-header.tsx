/** Serif page title and a short description; the sidebar and loop give the context. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex max-w-[760px] flex-col gap-1.5">
        <h1 className="font-serif text-[34px] leading-[1.05] font-normal tracking-[-0.01em] text-foreground sm:text-[40px]">
          {title}
        </h1>
        {description ? <p className="text-body leading-normal text-foreground-2">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
