/**
 * APPLICATION namespace layout: the authenticated shell.
 *
 * Package 1 provides the structural shell only. There is no session gate here
 * yet — and when it arrives it will be a server-side check against the backend,
 * never a client-side condition. Nothing in this layout grants access.
 */

import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { APPLICATION_NAVIGATION } from "@/components/shell/navigation";

export default function ApplicationLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      navigation={APPLICATION_NAVIGATION}
      navigationLabel="Workspace"
      namespaceLabel="Application"
    >
      {children}
    </AppShell>
  );
}
