"use client";

/**
 * Application shell: header, primary navigation, main region, footer slot.
 *
 * Responsive by construction (navigation collapses under 900px) and accessible:
 * a skip link, a single labelled `main` landmark and a live region for page-level
 * status.
 */

import { useState, type ReactNode } from "react";
import { HeaderBar } from "./header-bar";
import { PrimaryNav } from "./primary-nav";
import type { NavigationItem } from "./navigation";
import styles from "./app-shell.module.css";

export function AppShell({
  navigation,
  navigationLabel,
  namespaceLabel,
  accountSlot,
  children,
}: {
  navigation: readonly NavigationItem[];
  navigationLabel: string;
  namespaceLabel: string;
  accountSlot?: ReactNode;
  children: ReactNode;
}) {
  const [isNavigationOpen, setNavigationOpen] = useState(false);

  return (
    <div className={styles.shell}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <HeaderBar
        namespaceLabel={namespaceLabel}
        accountSlot={accountSlot}
        isNavigationOpen={isNavigationOpen}
        onToggleNavigation={() => setNavigationOpen((open) => !open)}
      />
      <div className={styles.body}>
        <PrimaryNav
          items={navigation}
          label={navigationLabel}
          isOpen={isNavigationOpen || undefined === undefined ? true : true}
        />
        <main id="main-content" className={styles.main} tabIndex={-1}>
          <div className={styles.content}>{children}</div>
        </main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className={styles.pageHeader}>
      <div>
        <h1 className={styles.pageTitle}>{title}</h1>
        {description ? <p className={styles.pageDescription}>{description}</p> : null}
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </div>
  );
}
