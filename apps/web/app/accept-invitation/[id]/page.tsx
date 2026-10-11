import type { Metadata } from "next";
import { headers } from "next/headers";
import { Logo } from "@/components/brand";
import { AcceptInvitation } from "@/components/org/accept-invitation";
import { Alert } from "@/components/ui/primitives";
import { auth } from "@/lib/auth";
import { requireSession } from "@/lib/session";

export const metadata: Metadata = { title: "Accept invitation" };

export default async function AcceptInvitationPage({ params }: PageProps<"/accept-invitation/[id]">) {
  const { id } = await params;
  const session = await requireSession(`/accept-invitation/${id}`);
  let invitation: Awaited<ReturnType<typeof auth.api.getInvitation>> | null = null;
  try {
    invitation = await auth.api.getInvitation({ headers: await headers(), query: { id } });
  } catch {
    invitation = null;
  }
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="px-6 py-5">
        <Logo />
      </header>
      <main className="mx-auto w-full max-w-sm px-4 pt-[8vh]">
        {!invitation ? (
          <Alert tone="error" title="Invitation not available">
            This invitation does not exist, has expired, or was sent to a different email address than{" "}
            {session.user.email}.
          </Alert>
        ) : (
          <>
            <h1 className="text-xl font-semibold tracking-[-0.02em]">Join {invitation.organizationName}</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">
              {invitation.inviterEmail} invited you to join as <span className="text-foreground">{invitation.role}</span>.
            </p>
            <AcceptInvitation invitationId={id} organizationId={invitation.organizationId} />
          </>
        )}
      </main>
    </div>
  );
}
