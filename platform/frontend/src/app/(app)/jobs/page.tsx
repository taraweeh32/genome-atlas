import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { JobsView } from "./jobs-view";

export const metadata: Metadata = { title: "Jobs" };

/**
 * Job monitoring for the caller's own scopes.
 *
 * This is the durable work record, not a browser task list: claiming, leases,
 * heartbeats, retries and cancellation all happen on the server, and the caller
 * sees only jobs belonging to a scope they may read.
 */
export default function JobsPage() {
  return (
    <>
      <PageHeader
        title="Jobs"
        description="Durable background work: queue, priority, attempts, leases and failures as recorded by the platform. A retry backoff and an ordinary queue wait are shown as different states."
      />
      <JobsView />
    </>
  );
}
