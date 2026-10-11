"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/primitives";
import { authClient } from "@/lib/auth-client";

export function AcceptInvitation({ invitationId, organizationId }: { invitationId: string; organizationId: string }) {
  const router = useRouter();
  const [pending, setPending] = React.useState<"accept" | "reject" | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <div className="mt-6 grid gap-3">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex gap-2">
        <Button
          variant="primary"
          loading={pending === "accept"}
          disabled={pending !== null}
          onClick={async () => {
            setPending("accept");
            const { error } = await authClient.organization.acceptInvitation({ invitationId });
            if (error) {
              setError(error.message ?? "Could not accept the invitation");
              setPending(null);
              return;
            }
            await authClient.organization.setActive({ organizationId });
            router.push("/projects");
            router.refresh();
          }}
        >
          Accept invitation
        </Button>
        <Button
          variant="ghost"
          loading={pending === "reject"}
          disabled={pending !== null}
          onClick={async () => {
            setPending("reject");
            await authClient.organization.rejectInvitation({ invitationId });
            router.push("/");
          }}
        >
          Decline
        </Button>
      </div>
    </div>
  );
}
