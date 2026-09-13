import type { Metadata } from "next";
import { Suspense } from "react";
import { VerifyForm } from "@/components/auth/verify-form";
import { LoadingState } from "@/components/ui/states";

export const metadata: Metadata = { title: "Verify your email" };

/** Email-verification route. Tokens are validated and consumed server-side. */
export default function VerifyPage() {
  return (
    <>
      <h1>Verify your email</h1>
      <Suspense fallback={<LoadingState label="Preparing verification" />}>
        <VerifyForm />
      </Suspense>
    </>
  );
}
