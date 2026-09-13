import { redirect } from "next/navigation";

/**
 * Entry point. The authenticated application area owns the landing experience;
 * a later package redirects unauthenticated visitors to /login from the
 * server-verified session, never from a client-side check.
 */
export default function RootPage() {
  redirect("/dashboard");
}
