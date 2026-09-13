"use client";

/**
 * Button foundation.
 *
 * Variants include an explicit `danger` variant, because destructive operations
 * must be visually distinct. Confirmation flows and the authorization decision
 * behind a destructive action are owned by later packages and by the backend.
 */

import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./button.module.css";

export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Renders a busy state and blocks interaction without shifting layout. */
  isBusy?: boolean;
  children: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  isBusy = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={rest.type ?? "button"}
      className={[styles.button, styles[variant], styles[size], className]
        .filter(Boolean)
        .join(" ")}
      disabled={disabled || isBusy}
      aria-busy={isBusy || undefined}
      {...rest}
    >
      {children}
    </button>
  );
}
