import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { SignUpForm } from "@/components/auth/auth-forms";
import { googleConfigured, smtpConfigured } from "@/lib/env";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Create account" };

export default async function SignUpPage({ searchParams }: PageProps<"/sign-up">) {
  if (await getSession()) redirect("/projects");
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : undefined;
  return <SignUpForm google={googleConfigured()} next={next} devMailbox={!smtpConfigured()} />;
}
