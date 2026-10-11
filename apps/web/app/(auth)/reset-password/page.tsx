import type { Metadata } from "next";
import Link from "next/link";
import { AuthHeading, ResetPasswordForm } from "@/components/auth/auth-forms";
import { Alert } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Set a new password" };

export default async function ResetPasswordPage({ searchParams }: PageProps<"/reset-password">) {
  const { token, error } = await searchParams;
  if (typeof token !== "string" || error) {
    return (
      <>
        <AuthHeading title="Reset link invalid" />
        <Alert tone="error">This password reset link is invalid or has expired.</Alert>
        <p className="mt-5 text-sm">
          <Link href="/forgot-password" className="text-accent hover:underline">
            Request a new link
          </Link>
        </p>
      </>
    );
  }
  return (
    <>
      <AuthHeading title="Set a new password" />
      <ResetPasswordForm token={token} />
    </>
  );
}
