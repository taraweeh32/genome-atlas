import type { Metadata } from "next";
import { RegisterForm } from "@/components/auth/register-form";

export const metadata: Metadata = { title: "Create an account" };

/**
 * Registration route. Account creation, email verification and personal
 * workspace provisioning are backend-owned; registration never signs anyone in.
 */
export default function RegisterPage() {
  return (
    <>
      <h1>Create an account</h1>
      <RegisterForm />
    </>
  );
}
