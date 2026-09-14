import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { QueryWorkbench } from "./query-workbench";

export const metadata: Metadata = { title: "Variant query" };

/**
 * Variant query route: filtering, prioritization, paging and saved views.
 *
 * Filtering and prioritization are two independent configurations. The server
 * validates, executes and records each one; the browser only assembles them and
 * reads bounded pages. Nothing displayed here is computed client-side, and a
 * prioritization score is an ordering aid, not a clinical conclusion.
 */
export default function VariantQueryPage() {
  return (
    <>
      <PageHeader
        title="Variant query"
        description="Filter a result set with nested conditions, optionally prioritize the matches with a declared score, and page through the result. Filtering decides membership; prioritization only decides order."
      />
      <QueryWorkbench />
    </>
  );
}
