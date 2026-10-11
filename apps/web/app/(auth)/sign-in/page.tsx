import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthHeading, SignInForm } from "@/components/auth/auth-forms";
import { Alert } from "@/components/ui/primitives";
import { googleConfigured, smtpConfigured } from "@/lib/env";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in" };

export default async function SignInPage({ searchParams }: PageProps<"/sign-in">) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : undefined;
  if (await getSession()) redirect(next && next.startsWith("/") && !next.startsWith("//") ? next : "/projects");
  return (
    <>
      <AuthHeading title="Sign in to TraceLens" />
      {params.reset ? (
        <Alert tone="ok" className="mb-4">
          Password updated. Sign in with your new password.
        </Alert>
      ) : null}
      {params.error ? (
        <Alert tone="error" className="mb-4">
          Sign-in failed ({String(params.error).replaceAll("_", " ")}). Try again.
        </Alert>
      ) : null}
      <SignInForm google={googleConfigured()} next={next} devMailbox={!smtpConfigured()} />
    </>
  );
}
