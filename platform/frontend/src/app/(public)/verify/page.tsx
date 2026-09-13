import type { Metadata } from "next";
import styles from "../public.module.css";

export const metadata: Metadata = { title: "Verify your email" };

/** Email-verification route foundation. Token validation happens server-side. */
export default function VerifyPage() {
  return (
    <>
      <h1>Verify your email</h1>
      <p className={styles.notice}>
        Email verification is not implemented yet. The verification token will be validated by the
        backend; the frontend only reports the outcome.
      </p>
    </>
  );
}
