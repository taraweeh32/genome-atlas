import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { OrganizationsView } from "./organizations-view";

export const metadata: Metadata = { title: "Organizations" };

/**
 * Organizations route.
 *
 * A user may belong to no organization at all; that is a normal state, not an
 * error. Creating an organization is a *request* a platform administrator
 * decides — the frontend cannot approve one.
 */
export default function OrganizationsPage() {
  return (
    <>
      <PageHeader
        title="Organizations"
        description="Organization membership is granted explicitly. Membership alone never grants access to a project."
      />
      <OrganizationsView />
    </>
  );
}
