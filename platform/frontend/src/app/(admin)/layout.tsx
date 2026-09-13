/**
 * ADMINISTRATION namespace layout.
 *
 * Platform administration and organization administration are separate
 * authorities. The session gate below only avoids rendering the shell to an
 * anonymous visitor: whether the caller may perform any administrative action is
 * decided by the backend on every request, and an unauthorized call is refused
 * there even if this shell rendered.
 */

import type { ReactNode } from "react";
import { RequireSession } from "@/components/auth/require-session";
import { AccountMenu } from "@/components/shell/account-menu";
import { AppShell } from "@/components/shell/app-shell";
import { ADMINISTRATION_NAVIGATION } from "@/components/shell/navigation";

export default function AdministrationLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      navigation={ADMINISTRATION_NAVIGATION}
      navigationLabel="Administration"
      namespaceLabel="Administration"
      accountSlot={<AccountMenu />}
    >
      <RequireSession>{children}</RequireSession>
    </AppShell>
  );
}
