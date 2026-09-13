import type { Metadata } from "next";
import styles from "../public.module.css";

export const metadata: Metadata = { title: "Sign in" };

/**
 * Sign-in route foundation.
 *
 * Package 1 deliberately renders no credential form: authentication, sessions,
 * password hashing and MFA are implemented server-side in a later package. A
 * temporary client-side login would violate the security invariants.
 */
export default function LoginPage() {
  return (
    <>
      <h1>Sign in</h1>
      <p className={styles.notice}>
        Authentication is not implemented yet. This route reserves the public sign-in namespace so
        the real, backend-owned flow can be added without restructuring the shell.
      </p>
    </>
  );
}
