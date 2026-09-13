import type { Metadata } from "next";
import { RecoverForm } from "@/components/auth/recover-form";

export const metadata: Metadata = { title: "Account recovery" };

/**
 * Account recovery route. Reset tokens, rate limiting, single use and session
 * revocation are all enforced by the backend.
 */
export default function RecoverPage() {
  return (
    <>
      <h1>Account recovery</h1>
      <RecoverForm />
    </>
  );
}
