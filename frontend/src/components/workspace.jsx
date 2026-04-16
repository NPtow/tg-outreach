function cx(...parts) {
  return parts.filter(Boolean).join(" ");
}

const STAT_TONES = {
  neutral: "border-white/8 bg-white/4 text-zinc-100",
  blue: "border-sky-400/18 bg-sky-400/10 text-sky-100",
  emerald: "border-emerald-400/20 bg-emerald-400/10 text-emerald-100",
  amber: "border-amber-400/20 bg-amber-400/10 text-amber-100",
  rose: "border-rose-400/20 bg-rose-400/10 text-rose-100",
  violet: "border-violet-400/20 bg-violet-400/10 text-violet-100",
};

export function StatCard({ label, value, tone = "neutral", caption }) {
  return (
    <div className={cx(
      "rounded-2xl border px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]",
      STAT_TONES[tone] || STAT_TONES.neutral,
    )}>
      <div className="text-[11px] uppercase tracking-[0.24em] text-zinc-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      {caption ? <div className="mt-1 text-xs text-zinc-400">{caption}</div> : null}
    </div>
  );
}

export function PageHeader({ eyebrow, title, description, actions, stats, className = "" }) {
  return (
    <section className={cx("mb-7 space-y-5", className)}>
      <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
        <div className="max-w-3xl">
          {eyebrow ? (
            <div className="mb-3 inline-flex items-center rounded-full border border-white/10 bg-white/4 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-zinc-400">
              {eyebrow}
            </div>
          ) : null}
          <h1 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
          {description ? <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400 sm:text-[15px]">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2.5">{actions}</div> : null}
      </div>
      {stats?.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat) => (
            <StatCard key={stat.label} {...stat} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function Surface({ children, className = "", glow = false }) {
  return (
    <section
      className={cx(
        "rounded-[28px] border border-white/10 bg-[linear-gradient(180deg,rgba(24,24,31,0.94),rgba(10,10,15,0.94))] shadow-[0_24px_80px_rgba(0,0,0,0.35)] backdrop-blur-xl",
        glow ? "ring-1 ring-sky-400/10" : "",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function EmptyState({ icon, title, description, action, compact = false, className = "" }) {
  return (
    <div
      className={cx(
        "flex flex-col items-center justify-center rounded-[28px] border border-dashed border-white/12 bg-white/[0.02] px-6 text-center",
        compact ? "min-h-[220px] py-10" : "min-h-[320px] py-14",
        className,
      )}
    >
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-3xl shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
        {icon}
      </div>
      <h2 className="mt-5 text-lg font-medium text-white">{title}</h2>
      {description ? <p className="mt-2 max-w-md text-sm leading-6 text-zinc-400">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function SectionLabel({ title, description, action, className = "" }) {
  return (
    <div className={cx("mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-[0.22em] text-zinc-500">{title}</h2>
        {description ? <p className="mt-2 text-sm text-zinc-400">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
