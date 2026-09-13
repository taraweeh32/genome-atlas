/**
 * ADMINISTRATION namespace layout.
 *
 * The namespace exists so the control plane can be built without restructuring
 * the shell. It grants nothing: Package 1 implements no administrator role and no
 * privileged access. Every administration route will be authorized server-side,
 * with platform-administrator and organization-administrator scopes kept
 * distinct, and stronger controls for privileged actions.
 */

import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { ADMINISTRATION_NAVIGATION } from "@/components/shell/navigation";

export default function AdministrationLayout({ children }: { children: ReactNode }) {
  return (
    <AppShell
      navigation={ADMINISTRATION_NAVIGATION}
      navigationLabel="Administration"
      namespaceLabel="Administration"
    >
      {children}
    </AppShell>
  );
}
