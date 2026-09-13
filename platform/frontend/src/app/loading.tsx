import { LoadingState } from "@/components/ui/states";

/** Global route-level loading foundation. */
export default function GlobalLoading() {
  return (
    <div style={{ padding: "var(--space-6)" }}>
      <LoadingState label="Loading the platform" />
    </div>
  );
}
