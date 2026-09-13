import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { Card } from "@/components/ui/card";

export const metadata: Metadata = { title: "Administration" };

/**
 * Administration overview foundation.
 *
 * No administrative capability is implemented, and no administrative access is
 * simulated. This route reserves the namespace only.
 */
export default function AdministrationOverviewPage() {
  return (
    <>
      <PageHeader
        title="Administration"
        description="Namespace foundation. No administrative capability is active in this release."
      />
      <Card title="Access model">
        <p>
          Platform administration and organization administration are separate authorities.
          Organization administrators cannot approve organizations, manage platform infrastructure,
          alter other organizations or control global scientific resources. Scientific reviewer
          permissions are separate from administrative permissions.
        </p>
      </Card>
      <Card title="Authorization">
        <p>
          Every action in this namespace is authorized by the backend at the point of execution.
          Hiding a navigation entry is a presentation concern only and is never treated as a
          security control.
        </p>
      </Card>
    </>
  );
}
