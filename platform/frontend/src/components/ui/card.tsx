/** Card / panel foundation used by shell surfaces and later data modules. */

import type { ReactNode } from "react";
import styles from "./card.module.css";

export function Card({
  title,
  description,
  actions,
  children,
  headingLevel = 2,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
  headingLevel?: 2 | 3 | 4;
}) {
  const Heading = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <section className={styles.card}>
      {title ? (
        <header className={styles.header}>
          <div>
            <Heading className={styles.title}>{title}</Heading>
            {description ? <p className={styles.description}>{description}</p> : null}
          </div>
          {actions ? <div className={styles.actions}>{actions}</div> : null}
        </header>
      ) : null}
      {children ? <div className={styles.body}>{children}</div> : null}
    </section>
  );
}

export function DefinitionList({
  items,
}: {
  items: readonly { readonly term: string; readonly value: ReactNode }[];
}) {
  return (
    <dl className={styles.definitionList}>
      {items.map((item) => (
        <div key={item.term} className={styles.definitionRow}>
          <dt className={styles.definitionTerm}>{item.term}</dt>
          <dd className={styles.definitionValue}>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
