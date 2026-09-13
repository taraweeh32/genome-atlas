"use client";

/** Labelled form field used by the public identity flows. */

import type { InputHTMLAttributes } from "react";
import styles from "./auth-form.module.css";

export function Field({
  id,
  label,
  hint,
  ...rest
}: { id: string; label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <input id={id} className={styles.input} {...rest} />
      {hint ? <p className={styles.hint}>{hint}</p> : null}
    </div>
  );
}

export { styles as authStyles };
