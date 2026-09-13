import Link from "next/link";
import { EmptyState } from "@/components/ui/states";

/**
 * Not-found page.
 *
 * Deliberately identical for "does not exist" and "not visible to you": the
 * frontend must never confirm the existence of a resource the backend withheld.
 */
export default function NotFound() {
  return (
    <div style={{ padding: "var(--space-6)" }}>
      <EmptyState
        title="Page not available"
        description="This page does not exist, or it is not available to your account."
        action={<Link href="/dashboard">Return to the dashboard</Link>}
      />
    </div>
  );
}
