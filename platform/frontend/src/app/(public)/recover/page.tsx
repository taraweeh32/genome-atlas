import type { Metadata } from "next";
import styles from "../public.module.css";

export const metadata: Metadata = { title: "Account recovery" };

/** Account-recovery route foundation. */
export default function RecoverPage() {
  return (
    <>
      <h1>Account recovery</h1>
      <p className={styles.notice}>
        Account recovery is not implemented yet. Recovery tokens, rate limiting and notification
        delivery are backend responsibilities.
      </p>
    </>
  );
}
