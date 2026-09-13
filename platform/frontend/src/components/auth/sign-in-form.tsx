"use client";

/**
 * Sign-in form.
 *
 * The form collects credentials and shows the backend's verbatim answer. It
 * makes no authentication decision, applies no client-side lockout and never
 * distinguishes an unknown address from a wrong password — the backend answers
 * both identically on purpose.
 */

import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { Field, authStyles as styles } from "./field";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { useSession } from "@/context/session-context";
import { ApiError } from "@/lib/api-client";

export function SignInForm() {
  const { signIn } = useSession();
  const router = useRouter();
  const search = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isBusy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ message: string; correlationId?: string } | null>(null);

  const destination = search?.get("next") ?? "/dashboard";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await signIn(email, password);
      router.replace(destination.startsWith("/") ? destination : "/dashboard");
    } catch (cause) {
      setFailure({
        message:
          cause instanceof ApiError
            ? cause.message
            : "The platform API could not be reached. Try again shortly.",
        correlationId: cause instanceof ApiError ? cause.correlationId : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {failure ? (
        <ErrorState
          title="Sign-in was refused"
          description={failure.message}
          correlationId={failure.correlationId}
        />
      ) : null}
      <Field
        id="email"
        label="Email address"
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        id="password"
        label="Password"
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <div className={styles.actions}>
        <Button type="submit" variant="primary" isBusy={isBusy}>
          Sign in
        </Button>
      </div>
      <p className={styles.links}>
        <Link href="/register">Create an account</Link>
        <Link href="/recover">Forgotten password</Link>
        <Link href="/verify">Verify an email address</Link>
      </p>
    </form>
  );
}
