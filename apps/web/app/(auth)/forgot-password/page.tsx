import type { Metadata } from "next";
import Link from "next/link";
import { AuthHeading, ForgotPasswordForm } from "@/components/auth/auth-forms";
import { smtpConfigured } from "@/lib/env";

export const metadata: Metadata = { title: "Reset password" };

export default function ForgotPasswordPage() {
  return (
    <>
      <AuthHeading title="Reset your password">Enter your email and we will send you a reset link.</AuthHeading>
      <ForgotPasswordForm devMailbox={!smtpConfigured()} />
      <p className="mt-5 text-sm">
        <Link href="/sign-in" className="text-muted-foreground hover:text-foreground">
          Back to sign in
        </Link>
      </p>
    </>
  );
}
