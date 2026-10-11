"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { createProject } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogTrigger } from "@/components/ui/overlays";
import { Alert } from "@/components/ui/primitives";

export function CreateProjectButton({ orgId }: { orgId: string }) {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setName("");
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="primary">
          <Plus /> New project
        </Button>
      </DialogTrigger>
      <DialogContent title="New project" description="You can create API keys for it right after.">
        <form
          className="grid gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setPending(true);
            setError(null);
            const result = await createProject(orgId, name.trim());
            setPending(false);
            if (!result.ok) {
              setError(result.error);
              return;
            }
            setOpen(false);
            router.push(`/p/${result.data.id}/settings?created=1`);
            router.refresh();
          }}
        >
          <Field label="Project name" htmlFor="project-name">
            <Input id="project-name" required maxLength={80} autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" loading={pending} disabled={!name.trim()}>
              Create project
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
