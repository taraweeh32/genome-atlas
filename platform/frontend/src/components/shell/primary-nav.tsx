"use client";

/** Primary navigation rendered from the navigation model. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { isActive, type NavigationItem } from "./navigation";
import styles from "./primary-nav.module.css";

export function PrimaryNav({
  items,
  label,
  isOpen = true,
}: {
  items: readonly NavigationItem[];
  label: string;
  isOpen?: boolean;
}) {
  const pathname = usePathname() ?? "/";

  return (
    <nav
      id="primary-navigation"
      className={`${styles.nav} ${isOpen ? styles.open : styles.closed}`}
      aria-label={label}
    >
      <p className={styles.sectionLabel}>{label}</p>
      <ul className={styles.list}>
        {items.map((item) => {
          const active = isActive(item, pathname);
          if (!item.available) {
            // Unimplemented modules are announced as such, never linked to a
            // fake page.
            return (
              <li key={item.id}>
                <span className={styles.unavailable} aria-disabled="true">
                  {item.label}
                  <span className={styles.badge}>Not yet available</span>
                </span>
              </li>
            );
          }
          return (
            <li key={item.id}>
              <Link
                href={item.href}
                className={`${styles.link} ${active ? styles.active : ""}`}
                aria-current={active ? "page" : undefined}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
