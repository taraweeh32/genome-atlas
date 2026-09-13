"use client";

/**
 * Notification / toast infrastructure foundation.
 *
 * This is transient UI feedback only. It is NOT the notification domain (durable,
 * per-user, backend-owned) that a later package introduces.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import styles from "./toast.module.css";

export type ToastTone = "info" | "success" | "warning" | "danger";

export interface Toast {
  readonly id: string;
  readonly tone: ToastTone;
  readonly title: string;
  readonly description?: string;
  /** Correlation ID from a failed API call, so support can trace it. */
  readonly correlationId?: string;
}

export interface ToastContextValue {
  readonly toasts: readonly Toast[];
  publish(toast: Omit<Toast, "id">): string;
  dismiss(id: string): void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let counter = 0;
function nextId(): string {
  counter += 1;
  return `toast-${counter}`;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<readonly Toast[]>([]);

  const publish = useCallback((toast: Omit<Toast, "id">) => {
    const id = nextId();
    setToasts((current) => [...current, { ...toast, id }]);
    return id;
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({ toasts, publish, dismiss }),
    [toasts, publish, dismiss],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Polite live region: announced without stealing focus. */}
      <div className={styles.region} role="region" aria-live="polite" aria-label="Notifications">
        {toasts.map((toast) => (
          <div key={toast.id} className={`${styles.toast} ${styles[toast.tone]}`}>
            <div>
              <p className={styles.title}>{toast.title}</p>
              {toast.description ? (
                <p className={styles.description}>{toast.description}</p>
              ) : null}
              {toast.correlationId ? (
                <p className={styles.correlation}>Reference: {toast.correlationId}</p>
              ) : null}
            </div>
            <button
              type="button"
              className={styles.dismiss}
              onClick={() => dismiss(toast.id)}
              aria-label={`Dismiss notification: ${toast.title}`}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToasts(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error("useToasts must be used inside a ToastProvider");
  }
  return value;
}
