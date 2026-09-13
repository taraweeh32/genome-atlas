/**
 * APPLICATION namespace layout: the authenticated shell.
 *
 * The session gate here is a presentation concern only. Authorization for every
 * operation is decided by the backend at the point of execution; hiding a route
 * or a control is never treated as a security control.
 */

import type { ReactNode } from "react";
import { RequireSession } from "@/components/auth/require-session";
import { AccountMenu } from "@/components/shell/account-menu";
import { AppShell } from "@/components/shell/app-shell";
import { APPLICATION_NAVIGATION } from "@/components/shell/navigation";

export default function ApplicationLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      navigation={APPLICATION_NAVIGATION}
      navigationLabel="Workspace"
      namespaceLabel="Application"
      accountSlot={<AccountMenu />}
    >
      <RequireSession>{children}</RequireSession>
    </AppShell>
  );
}
