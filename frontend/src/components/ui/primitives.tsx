import clsx from "clsx";
import { TriangleAlert, CircleCheck, CircleDashed, LoaderCircle, RotateCcw, CircleX } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "neutral" | "terracotta" | "indigo" | "ochre" | "moss" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "bg-sand text-ink-soft border-sandstone",
  terracotta: "bg-terracotta-soft text-terracotta-dark border-terracotta/20",
  indigo: "bg-indigo-soft text-indigo-ink border-indigo-ink/15",
  ochre: "bg-ochre-soft text-[#7a3a06] border-ochre/25",
  moss: "bg-moss-soft text-moss border-moss/20",
  danger: "bg-danger-soft text-danger border-danger/20",
};

export function Badge({
  tone = "neutral",
  className,
  children,
  title,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const STATUS: Record<string, { tone: Tone; label: string; icon: typeof CircleCheck; spin?: boolean }> = {
  ready: { tone: "moss", label: "Ready", icon: CircleCheck },
  succeeded: { tone: "moss", label: "Done", icon: CircleCheck },
  queued: { tone: "neutral", label: "Queued", icon: CircleDashed },
  processing: { tone: "ochre", label: "Processing", icon: LoaderCircle, spin: true },
  leased: { tone: "ochre", label: "Running", icon: LoaderCircle, spin: true },
  failed: { tone: "danger", label: "Failed", icon: RotateCcw },
  dead: { tone: "danger", label: "Gave up", icon: CircleX },
};

/** Status is always conveyed by icon + text, never colour alone (WCAG 1.4.1). */
export function StatusPill({ status, className }: { status: string; className?: string }) {
  const s = STATUS[status] ?? { tone: "neutral" as Tone, label: status, icon: CircleDashed };
  const Icon = s.icon;
  return (
    <Badge tone={s.tone} className={className}>
      <Icon aria-hidden className={clsx("size-3.5", s.spin && "animate-spin")} />
      {s.label}
    </Badge>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={clsx("animate-pulse rounded-lg bg-sandstone/60", className)} />;
}

export function LoadingBlock({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={clsx("flex items-center gap-2 py-8 text-muted", className)}>
      <LoaderCircle aria-hidden className="size-5 animate-spin" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  icon,
  className,
}: {
  title: string;
  children?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "flex flex-col items-center gap-2 rounded-[var(--radius-card)] border border-dashed border-sandstone-dark bg-sand/50 px-6 py-10 text-center",
        className,
      )}
    >
      {icon}
      <p className="font-serif text-xl font-semibold">{title}</p>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div
      role="alert"
      className={clsx(
        "flex flex-col items-start gap-3 rounded-[var(--radius-card)] border border-danger/25 bg-danger-soft/60 p-5",
        className,
      )}
    >
      <div className="flex items-center gap-2 font-semibold text-danger">
        <TriangleAlert aria-hidden className="size-5" />
        Couldn&apos;t load this
      </div>
      <p className="text-sm text-ink-soft">{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="btn btn-secondary">
          <RotateCcw aria-hidden className="size-4" /> Try again
        </button>
      )}
    </div>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  children,
  id,
  className,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <div data-reveal className={clsx("mb-5 flex flex-wrap items-end justify-between gap-3", className)}>
      <div>
        {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
        <h2 id={id} className="text-3xl font-semibold">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-semibold tracking-wide text-muted uppercase">{label}</dt>
      <dd className="font-serif text-3xl font-semibold tabular-nums">{value}</dd>
      {hint && <dd className="text-xs text-muted">{hint}</dd>}
    </div>
  );
}
