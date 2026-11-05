"use client";

import { AlertCircle, ChevronLeft, ChevronRight, Inbox, Loader2, RefreshCw, X } from "lucide-react";
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { errorMessage } from "@/lib/api";
import { cx, humanize } from "@/lib/format";

// ------------------------------------------------------------------ buttons

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "xs" | "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-600 text-white hover:bg-accent-500 focus-visible:ring-accent-400 shadow-sm shadow-accent-900/40",
  secondary: "bg-zinc-800 text-zinc-100 hover:bg-zinc-700 border border-zinc-700 focus-visible:ring-zinc-500",
  ghost: "text-zinc-300 hover:bg-zinc-800 hover:text-zinc-100 focus-visible:ring-zinc-600",
  danger: "bg-rose-600/90 text-white hover:bg-rose-500 focus-visible:ring-rose-400",
  success: "bg-emerald-600 text-white hover:bg-emerald-500 focus-visible:ring-emerald-400",
};
const SIZES: Record<Size, string> = {
  xs: "h-7 px-2 text-xs gap-1",
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-md font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950 disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

// ------------------------------------------------------------------ form controls

const controlBase =
  "block w-full rounded-md border border-zinc-700 bg-zinc-900 text-sm text-zinc-100 placeholder:text-zinc-500 shadow-sm transition focus:border-accent-500 focus:outline-none focus:ring-2 focus:ring-accent-500/30 disabled:cursor-not-allowed disabled:opacity-60";

interface FieldWrapProps {
  id: string;
  label?: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  className?: string;
  children: ReactNode;
  required?: boolean;
}

export function FieldWrap({ id, label, hint, error, className, children, required }: FieldWrapProps) {
  return (
    <div className={cx("space-y-1.5", className)}>
      {label && (
        <label htmlFor={id} className="block text-xs font-medium uppercase tracking-wide text-zinc-400">
          {label}
          {required && <span className="ml-0.5 text-rose-400">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-rose-400">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-zinc-500">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

interface CommonFieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  wrapperClassName?: string;
}

export type InputProps = InputHTMLAttributes<HTMLInputElement> & CommonFieldProps;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, wrapperClassName, className, id, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldWrap id={fid} label={label} hint={hint} error={error} className={wrapperClassName} required={rest.required}>
      <input
        ref={ref}
        id={fid}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fid}-error` : hint ? `${fid}-hint` : undefined}
        className={cx(controlBase, "h-10 px-3", rest.type === "color" && "h-10 w-16 cursor-pointer p-1", error && "border-rose-500", className)}
        {...rest}
      />
    </FieldWrap>
  );
});

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & CommonFieldProps;

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { label, hint, error, wrapperClassName, className, id, rows = 3, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldWrap id={fid} label={label} hint={hint} error={error} className={wrapperClassName} required={rest.required}>
      <textarea
        ref={ref}
        id={fid}
        rows={rows}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fid}-error` : hint ? `${fid}-hint` : undefined}
        className={cx(controlBase, "px-3 py-2", error && "border-rose-500", className)}
        {...rest}
      />
    </FieldWrap>
  );
});

export type SelectOption = { value: string; label: string; disabled?: boolean };
export type SelectProps = SelectHTMLAttributes<HTMLSelectElement> &
  CommonFieldProps & { options: (SelectOption | string)[]; placeholder?: string };

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, wrapperClassName, className, id, options, placeholder, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldWrap id={fid} label={label} hint={hint} error={error} className={wrapperClassName} required={rest.required}>
      <select
        ref={ref}
        id={fid}
        aria-invalid={error ? true : undefined}
        className={cx(controlBase, "h-10 px-3 pr-8", error && "border-rose-500", className)}
        {...rest}
      >
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => {
          const opt = typeof o === "string" ? { value: o, label: humanize(o) } : o;
          return (
            <option key={opt.value} value={opt.value} disabled={opt.disabled}>
              {opt.label}
            </option>
          );
        })}
      </select>
    </FieldWrap>
  );
});

export function Checkbox({
  label,
  hint,
  checked,
  onChange,
  disabled,
  id,
}: {
  label: ReactNode;
  hint?: ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  id?: string;
}) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="flex items-start gap-2.5">
      <input
        id={fid}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 cursor-pointer rounded border-zinc-600 bg-zinc-900 text-accent-600 accent-accent-500 focus:ring-accent-500"
      />
      <label htmlFor={fid} className="cursor-pointer select-none text-sm text-zinc-200">
        {label}
        {hint && <span className="block text-xs text-zinc-500">{hint}</span>}
      </label>
    </div>
  );
}

/** JSON textarea with live validation. Calls onChange only with valid objects. */
export function JsonEditor({
  label,
  value,
  onChange,
  onValidity,
  rows = 10,
  hint,
  disabled,
}: {
  label?: ReactNode;
  value: unknown;
  onChange: (v: Record<string, unknown>) => void;
  onValidity?: (valid: boolean) => void;
  rows?: number;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [err, setErr] = useState<string | null>(null);
  const lastEmitted = useRef<string>(JSON.stringify(value ?? {}));

  useEffect(() => {
    const incoming = JSON.stringify(value ?? {});
    if (incoming !== lastEmitted.current) {
      lastEmitted.current = incoming;
      setText(JSON.stringify(value ?? {}, null, 2));
      setErr(null);
    }
  }, [value]);

  return (
    <Textarea
      label={label}
      rows={rows}
      value={text}
      disabled={disabled}
      spellCheck={false}
      className="font-mono text-xs leading-relaxed"
      error={err}
      hint={hint}
      onChange={(e) => {
        const t = e.target.value;
        setText(t);
        try {
          const parsed: unknown = t.trim() ? JSON.parse(t) : {};
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Must be a JSON object");
          setErr(null);
          onValidity?.(true);
          lastEmitted.current = JSON.stringify(parsed);
          onChange(parsed as Record<string, unknown>);
        } catch (ex) {
          setErr(`Invalid JSON: ${ex instanceof Error ? ex.message : String(ex)}`);
          onValidity?.(false);
        }
      }}
    />
  );
}

// ------------------------------------------------------------------ layout

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-xl border border-zinc-800 bg-zinc-900/60 shadow-sm", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, description, actions, className }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-wrap items-start justify-between gap-3 border-b border-zinc-800 px-5 py-4", className)}>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("p-5", className)}>{children}</div>;
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">{title}</h1>
        {description && <p className="mt-1 text-sm text-zinc-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ feedback

type Tone = "zinc" | "accent" | "green" | "amber" | "red" | "blue" | "purple";
const TONES: Record<Tone, string> = {
  zinc: "bg-zinc-800 text-zinc-300 ring-zinc-700",
  accent: "bg-accent-500/10 text-accent-300 ring-accent-500/30",
  green: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  amber: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  red: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  blue: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  purple: "bg-fuchsia-500/10 text-fuchsia-300 ring-fuchsia-500/30",
};

export function Badge({ tone = "zinc", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, Tone> = {
  // generic run / job
  queued: "zinc",
  running: "blue",
  succeeded: "green",
  failed: "red",
  cancelled: "zinc",
  // project
  draft: "zinc",
  generating: "blue",
  scripted: "accent",
  rendering: "blue",
  rendered: "purple",
  pending_approval: "amber",
  approved: "green",
  scheduled: "accent",
  published: "green",
  archived: "zinc",
  // publish
  uploading: "blue",
  processing: "blue",
  rejected: "red",
  // approvals / accounts
  pending: "amber",
  active: "green",
  expired: "amber",
  revoked: "red",
  error: "red",
  success: "green",
  skipped: "zinc",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  const tone = STATUS_TONES[s] ?? "zinc";
  const pulsing = s === "running" || s === "uploading" || s === "processing" || s === "generating" || s === "rendering";
  return (
    <Badge tone={tone}>
      {pulsing && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />}
      {humanize(s)}
    </Badge>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-5 w-5 animate-spin text-zinc-400", className)} aria-label="Loading" />;
}

export function LoadingBlock({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={cx("flex items-center justify-center gap-3 py-12 text-sm text-zinc-500", className)} role="status">
      <Spinner />
      {label}
    </div>
  );
}

export function EmptyState({ title, description, action, icon }: { title: string; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-zinc-800/80 p-3 text-zinc-400">{icon ?? <Inbox className="h-6 w-6" />}</div>
      <p className="text-sm font-medium text-zinc-200">{title}</p>
      {description && <p className="mt-1 max-w-md text-sm text-zinc-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  return (
    <div className={cx("flex flex-col items-center justify-center gap-3 px-6 py-10 text-center", className)} role="alert">
      <AlertCircle className="h-6 w-6 text-rose-400" />
      <p className="max-w-lg text-sm text-rose-300">{errorMessage(error)}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry} icon={<RefreshCw className="h-4 w-4" />}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{errorMessage(error)}</span>
    </div>
  );
}

export function Notice({ tone = "zinc", children, icon }: { tone?: "zinc" | "amber" | "accent" | "red" | "green"; children: ReactNode; icon?: ReactNode }) {
  const map = {
    zinc: "border-zinc-700 bg-zinc-800/40 text-zinc-300",
    amber: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    accent: "border-accent-500/30 bg-accent-500/10 text-accent-200",
    red: "border-rose-500/30 bg-rose-500/10 text-rose-200",
    green: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  } as const;
  return (
    <div className={cx("flex items-start gap-2 rounded-lg border px-4 py-3 text-sm", map[tone])}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function ProgressBar({ value, className, tone = "accent", label }: { value: number; className?: string; tone?: "accent" | "green" | "red" | "amber"; label?: string }) {
  const v = Math.max(0, Math.min(100, value || 0));
  const color = { accent: "bg-accent-500", green: "bg-emerald-500", red: "bg-rose-500", amber: "bg-amber-500" }[tone];
  return (
    <div
      className={cx("h-2 w-full overflow-hidden rounded-full bg-zinc-800", className)}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v)}
      aria-label={label}
    >
      <div className={cx("h-full rounded-full transition-[width] duration-500", color)} style={{ width: `${v}%` }} />
    </div>
  );
}

// ------------------------------------------------------------------ modal

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const t = setTimeout(() => {
      const el = ref.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-close])");
      el?.focus();
    }, 10);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      clearTimeout(t);
      document.body.style.overflow = "";
      prev?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;
  const width = { sm: "max-w-md", md: "max-w-xl", lg: "max-w-3xl", xl: "max-w-5xl" }[size];
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cx("relative flex max-h-[92vh] w-full flex-col rounded-t-xl border border-zinc-800 bg-zinc-900 shadow-2xl sm:rounded-xl", width)}
      >
        <div className="flex items-start justify-between gap-4 border-b border-zinc-800 px-5 py-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-zinc-100">
              {title}
            </h2>
            {description && <p className="mt-0.5 text-sm text-zinc-400">{description}</p>}
          </div>
          <button data-close onClick={onClose} className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200" aria-label="Close dialog">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-zinc-800 px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/** Button that asks for confirmation in a modal before running an async action. */
export function ConfirmButton({
  onConfirm,
  title,
  message,
  confirmLabel = "Confirm",
  variant = "danger",
  children,
  size = "sm",
  icon,
  disabled,
  buttonVariant,
  className,
  "aria-label": ariaLabel,
}: {
  onConfirm: () => Promise<unknown> | unknown;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  variant?: Variant;
  buttonVariant?: Variant;
  children?: ReactNode;
  size?: Size;
  icon?: ReactNode;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <Button size={size} variant={buttonVariant ?? "ghost"} icon={icon} disabled={disabled} onClick={() => setOpen(true)} className={className} aria-label={ariaLabel}>
        {children}
      </Button>
      <Modal
        open={open}
        onClose={() => !busy && setOpen(false)}
        title={title}
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant={variant}
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onConfirm();
                  setOpen(false);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {confirmLabel}
            </Button>
          </>
        }
      >
        <div className="text-sm text-zinc-300">{message}</div>
      </Modal>
    </>
  );
}

// ------------------------------------------------------------------ tabs

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { value: T; label: ReactNode; icon?: ReactNode; count?: number }[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={cx("-mx-1 overflow-x-auto", className)}>
      <div role="tablist" className="inline-flex min-w-full gap-1 border-b border-zinc-800 px-1">
        {tabs.map((t) => {
          const active = t.value === value;
          return (
            <button
              key={t.value}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(t.value)}
              className={cx(
                "-mb-px inline-flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
                active ? "border-accent-500 text-zinc-50" : "border-transparent text-zinc-400 hover:border-zinc-600 hover:text-zinc-200",
              )}
            >
              {t.icon}
              {t.label}
              {t.count !== undefined && <span className="rounded-full bg-zinc-800 px-1.5 text-xs text-zinc-400">{t.count}</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ data display

export function Stat({ label, value, hint, icon, tone }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "red" | "amber" | "green" }) {
  const toneCls = tone === "red" ? "text-rose-300" : tone === "amber" ? "text-amber-300" : tone === "green" ? "text-emerald-300" : "text-zinc-50";
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wide text-zinc-500">
        <span>{label}</span>
        {icon && <span className="text-zinc-600">{icon}</span>}
      </div>
      <div className={cx("mt-2 text-2xl font-semibold tabular-nums", toneCls)}>{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </Card>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="data-table w-full text-left text-sm">{children}</table>
    </div>
  );
}

export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="flex items-center justify-between gap-3 border-t border-zinc-800 px-5 py-3 text-sm text-zinc-400">
      <span>
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onChange(Math.max(0, offset - limit))} icon={<ChevronLeft className="h-4 w-4" />}>
          Prev
        </Button>
        <span className="tabular-nums">
          {page} / {pages}
        </span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

export function KeyValue({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs uppercase tracking-wide text-zinc-500">{k}</dt>
          <dd className="mt-0.5 break-words text-zinc-200">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Chips({ items, tone = "zinc" }: { items: string[]; tone?: Tone }) {
  if (!items.length) return <span className="text-zinc-500">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t, i) => (
        <Badge key={`${t}-${i}`} tone={tone}>
          {t}
        </Badge>
      ))}
    </div>
  );
}

export function NoAccess({ need }: { need: string }) {
  return (
    <Card>
      <EmptyState title="You don't have access to this page" description={`This area requires the ${need} role in the current organization.`} icon={<AlertCircle className="h-6 w-6" />} />
    </Card>
  );
}
