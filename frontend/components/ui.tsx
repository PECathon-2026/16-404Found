"use client";
import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import React, { useEffect, useRef } from "react";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

const TONES = {
  neutral: "text-neutral border-neutral/30 bg-neutral/10", running: "text-running border-running/30 bg-running/10", success: "text-success border-success/30 bg-success/10",
  warning: "text-warning border-warning/30 bg-warning/10", danger: "text-danger border-danger/30 bg-danger/10", critical: "text-critical border-critical/30 bg-critical/10",
  approval: "text-approval border-approval/30 bg-approval/10", accent: "text-accent border-accent/30 bg-accent/10",
};
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", children, icon, className, title }: { tone?: Tone; children: React.ReactNode; icon?: React.ReactNode; className?: string; title?: string }) {
  return <span title={title} className={cx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium leading-4 whitespace-nowrap", TONES[tone], className)}>{icon}{children}</span>;
}

export function Button({ variant = "secondary", size = "md", className, loading, children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; loading?: boolean }) {
  const v = {
    primary: "bg-accent text-accent-fg hover:opacity-90", secondary: "border border-line-strong bg-surface hover:bg-hover text-fg",
    ghost: "hover:bg-hover text-fg2", danger: "border border-danger/40 text-danger hover:bg-danger/10",
  }[variant];
  return (
    <button {...p} disabled={p.disabled || loading} className={cx("inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
      size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-3 text-sm", v, className)}>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}{children}
    </button>
  );
}

export function Card({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...p} className={cx("glass rounded-xl", className)}>{children}</div>;
}
export function CardHeader({ title, right, sub }: { title: React.ReactNode; right?: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
      <div className="min-w-0"><h3 className="truncate text-sm font-semibold">{title}</h3>{sub && <p className="text-xs text-fg3">{sub}</p>}</div>{right}
    </div>
  );
}
export const Skeleton = ({ className }: { className?: string }) => <div aria-hidden className={cx("animate-pulse rounded bg-hover", className)} />;
export const Mono = ({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) => <span title={title} className={cx("font-mono text-[12px]", className)}>{children}</span>;

/** lucide-react no longer ships brand icons; a minimal inline GitHub mark. */
export function Github({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export function EmptyState({ icon, title, description, action }: { icon?: React.ReactNode; title: string; description?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="text-fg3">{icon ?? <Inbox className="h-6 w-6" aria-hidden />}</div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {description && <p className="max-w-sm text-sm text-fg3">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorCard({ message, onRetry, title = "Something went wrong" }: { message: string; onRetry?: () => void; title?: string }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger/10 p-4">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
      <div className="min-w-0 flex-1"><p className="text-sm font-semibold text-danger">{title}</p><p className="break-words text-sm text-fg2">{message}</p></div>
      {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export class ErrorBoundary extends React.Component<{ children: React.ReactNode; label?: string }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) { return { err }; }
  render() {
    if (this.state.err) return <ErrorCard title={`${this.props.label ?? "This panel"} crashed`} message={this.state.err.message} onRetry={() => this.setState({ err: null })} />;
    return this.props.children;
  }
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && ref.current) {
        const f = ref.current.querySelectorAll<HTMLElement>('button,[href],input,textarea,select,[tabindex]:not([tabindex="-1"])');
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
        className={cx("dp-in flex max-h-[92vh] w-full flex-col rounded-t-xl border border-line bg-elevated shadow-[0_24px_80px_rgba(0,0,0,.65),0_0_0_1px_rgba(139,92,246,.25)] outline-none sm:rounded-xl", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3"><h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-fg3 hover:bg-hover"><X className="h-4 w-4" /></button></div>
        <div className="overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, label }: { tabs: { id: T; label: string; badge?: React.ReactNode }[]; value: T; onChange: (t: T) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-0.5 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cx("flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors", value === t.id ? "border-accent text-fg" : "border-transparent text-fg3 hover:text-fg")}>
          {t.label}{t.badge}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-fg2">{label}</span>{children}
      {hint && !error && <span className="block text-xs text-fg3">{hint}</span>}{error && <span role="alert" className="block text-xs text-danger">{error}</span>}
    </label>
  );
}
export const inputCls = "h-9 w-full rounded-md border border-line-strong bg-canvas px-3 text-sm text-fg placeholder:text-fg3 focus:border-accent";
export const textareaCls = "w-full rounded-md border border-line-strong bg-canvas px-3 py-2 text-sm text-fg placeholder:text-fg3 focus:border-accent";
