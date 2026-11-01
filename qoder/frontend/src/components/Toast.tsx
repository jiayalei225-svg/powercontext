import { useEffect } from "react";

export interface ToastState {
  id: number;
  tone: "ok" | "warn" | "error";
  text: string;
}

const ICONS = { ok: "✓", warn: "!", error: "×" } as const;

export function Toast({ toast, onDone }: { toast: ToastState | null; onDone: () => void }) {
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(onDone, 4200);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast?.id]);

  if (!toast) return null;
  return (
    <div className={`toast toast-${toast.tone}`} role="status" aria-live="polite">
      <span className="toast-icon">{ICONS[toast.tone]}</span>
      <span>{toast.text}</span>
      <button className="toast-close" onClick={onDone} aria-label="关闭提示">
        ×
      </button>
    </div>
  );
}
