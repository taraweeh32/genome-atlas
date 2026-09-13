/**
 * Root layout: the single html/body wrapper for every namespace.
 *
 * Providers established here are foundations only — workspace context and
 * transient notifications. No authentication, no permissions, no domain data.
 */

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { WorkspaceProvider } from "@/context/workspace-context";
import { ToastProvider } from "@/components/ui/toast";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: {
    default: "Genomic Analysis & Variant Interpretation Platform",
    template: "%s · Genomic Platform",
  },
  description:
    "Multi-tenant platform for genomic analysis and variant interpretation. Scientific computation runs in an independently deployable compute subsystem.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <WorkspaceProvider>
          <ToastProvider>{children}</ToastProvider>
        </WorkspaceProvider>
      </body>
    </html>
  );
}
