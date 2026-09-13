"use client";

/** Application header: product identity, workspace context and account slot. */

import Link from "next/link";
import type { ReactNode } from "react";
import { WorkspaceSwitcher } from "./workspace-switcher";
import styles from "./header-bar.module.css";

export function HeaderBar({
  namespaceLabel,
  onToggleNavigation,
  isNavigationOpen,
  accountSlot,
}: {
  namespaceLabel: string;
  onToggleNavigation?: () => void;
  isNavigationOpen?: boolean;
  accountSlot?: ReactNode;
}) {
  return (
    <header className={styles.header}>
      {onToggleNavigation ? (
        <button
          type="button"
          className={styles.navToggle}
          onClick={onToggleNavigation}
          aria-expanded={Boolean(isNavigationOpen)}
          aria-controls="primary-navigation"
        >
          <span className="visually-hidden">Toggle navigation</span>
          <span aria-hidden="true">☰</span>
        </button>
      ) : null}

      <Link href="/dashboard" className={styles.brand}>
        <span className={styles.brandMark} aria-hidden="true" />
        <span className={styles.brandName}>Genomic Platform</span>
      </Link>

      <span className={styles.namespace}>{namespaceLabel}</span>

      <div className={styles.spacer} />
      <WorkspaceSwitcher />
      <div className={styles.account}>{accountSlot}</div>
    </header>
  );
}
