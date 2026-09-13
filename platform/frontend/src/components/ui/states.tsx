/**
 * Loading, empty, error and degraded state foundations.
 *
 * Every data surface in later packages must render one of these explicitly.
 * None of them invent data: an empty state says "nothing here", never a fake
 * genomic dataset, and an error state surfaces the backend's message plus the
 * correlation ID for support.
 */

import type { ReactNode } from "react";
import styles from "./states.module.css";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className={styles.state} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <p className={styles.title}>{label}…</p>
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className={styles.skeletonGroup} role="status" aria-live="polite">
      <span className="visually-hidden">Loading content</span>
      {Array.from({ length: rows }, (_, index) => (
        <span key={index} className={styles.skeletonRow} aria-hidden="true" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className={styles.state}>
      <p className={styles.title}>{title}</p>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  correlationId,
  action,
}: {
  title?: string;
  description?: string;
  correlationId?: string;
  action?: ReactNode;
}) {
  return (
    <div className={`${styles.state} ${styles.error}`} role="alert">
      <p className={styles.title}>{title}</p>
      {description ? <p className={styles.description}>{description}</p> : null}
      {correlationId ? (
        <p className={styles.correlation}>
          Reference: <code>{correlationId}</code>
        </p>
      ) : null}
      {action}
    </div>
  );
}

/**
 * Degraded state: the platform is reachable but a dependency is impaired, so
 * some capabilities are unavailable. Distinct from an error.
 */
export function DegradedState({ description }: { description: string }) {
  return (
    <div className={`${styles.state} ${styles.degraded}`} role="status" aria-live="polite">
      <p className={styles.title}>Reduced functionality</p>
      <p className={styles.description}>{description}</p>
    </div>
  );
}
