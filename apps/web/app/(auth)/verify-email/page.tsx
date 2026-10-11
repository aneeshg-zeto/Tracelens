import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthHeading, ResendVerification } from "@/components/auth/auth-forms";
import { Alert } from "@/components/ui/primitives";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Verify email" };

export default async function VerifyEmailPage({ searchParams }: PageProps<"/verify-email">) {
  const { error } = await searchParams;
  const session = await getSession();
  if (session?.user.emailVerified && !error) redirect("/onboarding");
  return (
    <>
      <AuthHeading title={error ? "Verification failed" : "Verify your email"} />
      {error ? (
        <Alert tone="error">
          The verification link is invalid or has expired ({String(error).replaceAll("_", " ")}). Request a new one
          below.
        </Alert>
      ) : (
        <p className="text-sm text-muted-foreground">Open the link we emailed you to activate your account.</p>
      )}
      <ResendVerification email={session?.user.email} />
      <p className="mt-5 text-sm">
        <Link href="/sign-in" className="text-muted-foreground hover:text-foreground">
          Back to sign in
        </Link>
      </p>
    </>
  );
}
