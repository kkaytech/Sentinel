import { AlertTriangle, ShieldCheck, type LucideIcon } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Dialog({
  open,
  title,
  icon: Icon = ShieldCheck,
  tone,
  children,
  footer,
  onClose,
  wide,
}: {
  open: boolean;
  title: string;
  icon?: LucideIcon;
  tone?: "danger";
  children: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const focusable = ref.current?.querySelector<HTMLElement>("textarea, input, select, button.primary, button.danger-solid, button");
    focusable?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby="dialog-title" ref={ref}>
        <div className="dialog-head">
          <span className={`dialog-icon ${tone ?? ""}`} aria-hidden>
            <Icon />
          </span>
          <div style={{ paddingTop: 7 }}>
            <h2 id="dialog-title">{title}</h2>
          </div>
        </div>
        <div className="dialog-body">{children}</div>
        <div className="dialog-foot">{footer}</div>
      </div>
    </div>
  );
}

// A confirmation for an irreversible or accountable action.
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  danger,
  busy,
  onConfirm,
  onClose,
  confirmDisabled,
  icon,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
  confirmDisabled?: boolean;
  icon?: LucideIcon;
}) {
  return (
    <Dialog
      open={open}
      title={title}
      icon={icon ?? (danger ? AlertTriangle : ShieldCheck)}
      tone={danger ? "danger" : undefined}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className={`btn ${danger ? "danger-solid" : "primary"}`} onClick={onConfirm} disabled={busy || confirmDisabled}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
