/**
 * PUBLIC namespace layout: login, registration, account recovery, verification.
 *
 * Foundation only. No authentication is implemented in Package 1; these pages
 * carry no credential handling and no fake session.
 */

import type { ReactNode } from "react";
import styles from "./public.module.css";

export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.wrapper}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <main id="main-content" className={styles.panel} tabIndex={-1}>
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true" />
          <span>Genomic Analysis &amp; Variant Interpretation Platform</span>
        </div>
        {children}
      </main>
      <footer className={styles.footer}>
        <p>
          Access is governed by the platform administrator. All authorization decisions are made
          server-side.
        </p>
      </footer>
    </div>
  );
}
