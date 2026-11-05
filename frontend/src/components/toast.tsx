"use client";

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, errorMessage } from "@/lib/api";
import { cx } from "@/lib/format";

export type ToastKind = "success" | "error" | "info" | "warning";

interface Toast {
  id: number;
  kind: ToastKind;
  title?: string;
  message: string;
}

interface ToastApi {
  push: (kind: ToastKind, message: string, title?: string) => void;
  success: (message: string) => void;
  info: (message: string) => void;
  warning: (message: string) => void;
  /** Show an error from any thrown value (uses the API envelope message). */
  error: (err: unknown, title?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const ICONS = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle } as const;
const STYLES: Record<ToastKind, string> = {
  success: "border-emerald-500/30 text-emerald-300",
  error: "border-rose-500/30 text-rose-300",
  info: "border-accent-500/30 text-accent-300",
  warning: "border-amber-500/30 text-amber-300",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const push = useCallback(
    (kind: ToastKind, message: string, title?: string) => {
      const id = ++seq.current;
      setToasts((t) => [...t.slice(-4), { id, kind, message, title }]);
      setTimeout(() => dismiss(id), kind === "error" ? 8000 : 4500);
    },
    [dismiss],
  );

  const value = useMemo<ToastApi>(
    () => ({
      push,
      success: (m) => push("success", m),
      info: (m) => push("info", m),
      warning: (m) => push("warning", m),
      error: (err, title) => {
        let msg = errorMessage(err);
        if (err instanceof ApiError && err.validationErrors.length) {
          const first = err.validationErrors[0];
          msg = `${msg}: ${first.loc.slice(1).join(".")} — ${first.msg.replace(/^Value error, /, "")}`;
        }
        push("error", msg, title);
      },
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2 px-4 sm:px-0">
        {toasts.map((t) => {
          const Icon = ICONS[t.kind];
          return (
            <div
              key={t.id}
              role={t.kind === "error" ? "alert" : "status"}
              className={cx("toast-in pointer-events-auto flex items-start gap-3 rounded-lg border bg-zinc-900/95 p-3 shadow-xl backdrop-blur", STYLES[t.kind])}
            >
              <Icon className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                {t.title && <p className="font-medium text-zinc-100">{t.title}</p>}
                <p className="break-words text-zinc-300">{t.message}</p>
              </div>
              <button onClick={() => dismiss(t.id)} className="text-zinc-500 hover:text-zinc-200" aria-label="Dismiss notification">
                <X className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
