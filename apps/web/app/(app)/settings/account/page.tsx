import type { Metadata } from "next";
import { headers } from "next/headers";
import { AccountSettings } from "@/components/account/account-settings";
import { PageHeader } from "@/components/ui/primitives";
import { auth } from "@/lib/auth";
import { googleConfigured } from "@/lib/env";
import { requireSession } from "@/lib/session";

export const metadata: Metadata = { title: "Account" };

export default async function AccountPage() {
  const session = await requireSession("/settings/account");
  const h = await headers();
  const [sessions, accounts] = await Promise.all([auth.api.listSessions({ headers: h }), auth.api.listUserAccounts({ headers: h })]);

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Account" description="Your profile, sign-in methods, and active sessions." />
      <AccountSettings
        user={{ name: session.user.name, email: session.user.email, emailVerified: session.user.emailVerified }}
        currentSessionId={session.session.id}
        sessions={sessions.map((s) => ({
          id: s.id,
          token: s.token,
          userAgent: s.userAgent ?? null,
          ipAddress: s.ipAddress ?? null,
          createdAt: new Date(s.createdAt).toISOString(),
          expiresAt: new Date(s.expiresAt).toISOString(),
        }))}
        providers={accounts.map((a) => a.providerId)}
        googleAvailable={googleConfigured()}
      />
    </div>
  );
}
