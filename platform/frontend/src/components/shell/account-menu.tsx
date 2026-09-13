"use client";

/**
 * Account slot in the header.
 *
 * Reflects the session the backend reported. Signing out asks the backend to
 * revoke the session and then discards all client state; it never merely hides
 * the UI.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useSession } from "@/context/session-context";
import styles from "./account-menu.module.css";

export function AccountMenu() {
  const { status, identity, signOut } = useSession();
  const router = useRouter();
  const [isBusy, setBusy] = useState(false);

  if (status === "loading" || status === "unknown") {
    return (
      <span className={styles.pending} role="status">
        Checking session…
      </span>
    );
  }

  if (status !== "authenticated" || !identity) {
    return (
      <Link className={styles.signIn} href="/login">
        Sign in
      </Link>
    );
  }

  async function handleSignOut() {
    setBusy(true);
    try {
      await signOut(false);
      router.replace("/login");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.menu}>
      <span className={styles.account}>
        <span className={styles.name}>{identity.account.display_name}</span>
        <span className={styles.email}>{identity.account.email}</span>
      </span>
      <Button size="sm" variant="quiet" isBusy={isBusy} onClick={handleSignOut}>
        Sign out
      </Button>
    </div>
  );
}
