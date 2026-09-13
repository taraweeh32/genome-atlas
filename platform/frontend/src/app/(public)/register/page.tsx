import type { Metadata } from "next";
import styles from "../public.module.css";

export const metadata: Metadata = { title: "Create an account" };

/** Registration route foundation. Account creation is backend-owned (later package). */
export default function RegisterPage() {
  return (
    <>
      <h1>Create an account</h1>
      <p className={styles.notice}>
        Registration is not implemented yet. Account lifecycle, email verification and personal
        workspace provisioning are owned by the backend.
      </p>
    </>
  );
}
