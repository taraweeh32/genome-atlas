import type { Metadata } from "next";
import { Suspense } from "react";
import { SignInForm } from "@/components/auth/sign-in-form";
import { LoadingState } from "@/components/ui/states";

export const metadata: Metadata = { title: "Sign in" };

/**
 * Sign-in route.
 *
 * Credentials are verified by the backend, which issues an opaque server-side
 * session as an HttpOnly cookie plus a CSRF cookie. No token, password or
 * permission is ever stored in the browser by this page.
 */
export default function LoginPage() {
  return (
    <>
      <h1>Sign in</h1>
      <Suspense fallback={<LoadingState label="Preparing sign-in" />}>
        <SignInForm />
      </Suspense>
    </>
  );
}
