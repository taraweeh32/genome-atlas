import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { Card } from "@/components/ui/card";
import { AdministrationView } from "./administration-view";

export const metadata: Metadata = { title: "Administration" };

/**
 * Platform administration overview.
 *
 * Every panel here calls a platform-scoped endpoint. An organization
 * administrator cannot reach these operations: the backend refuses them, and the
 * refusal is shown plainly rather than hidden.
 */
export default function AdministrationOverviewPage() {
  return (
    <>
      <PageHeader
        title="Administration"
        description="Platform-scoped control plane. Organization administration is a separate authority."
      />
      <AdministrationView />
      <Card title="Access model">
        <p>
          Platform administration and organization administration are separate authorities.
          Organization administrators cannot approve organizations, manage platform infrastructure,
          alter other organizations or control global scientific resources. Scientific reviewer
          permissions are separate from administrative permissions.
        </p>
      </Card>
    </>
  );
}
