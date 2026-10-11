"use client";

import { Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { deleteTrace } from "@/app/actions";
import { Button } from "@/components/ui/button";

export function DeleteTraceButton({ projectId, traceId }: { projectId: string; traceId: string }) {
  const router = useRouter();
  const [busy, setBusy] = React.useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      loading={busy}
      onClick={async () => {
        if (!window.confirm("Delete this trace and all of its spans? This cannot be undone.")) return;
        setBusy(true);
        const res = await deleteTrace(projectId, traceId);
        setBusy(false);
        if (!res.ok) {
          toast.error(res.error);
          return;
        }
        toast.success("Trace deleted");
        router.push(`/p/${projectId}/traces`);
      }}
    >
      <Trash2 /> Delete
    </Button>
  );
}
