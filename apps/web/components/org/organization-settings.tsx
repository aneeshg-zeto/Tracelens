"use client";

import { MailPlus, MoreHorizontal, Trash2, UserMinus } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Select,
} from "@/components/ui/overlays";
import { Alert, Badge, EmptyState, Panel, PanelHeader } from "@/components/ui/primitives";
import { authClient } from "@/lib/auth-client";
import { formatDateTime, formatRelative } from "@/lib/utils";

type Member = { id: string; userId: string; role: string; createdAt: string; name: string; email: string };
type Invitation = { id: string; email: string; role: string; expiresAt: string };
type Role = "owner" | "admin" | "member" | "viewer";

const ROLE_OPTIONS: { value: Role; label: string; description: string }[] = [
  { value: "owner", label: "Owner", description: "Full control, including deleting projects and the organization" },
  { value: "admin", label: "Admin", description: "Manage members, projects, keys, and settings" },
  { value: "member", label: "Member", description: "Read traces, run evaluations and investigations" },
  { value: "viewer", label: "Viewer", description: "Read-only access" },
];

const roleTone = (role: string) => (role.includes("owner") ? "accent" : role.includes("admin") ? "info" : "neutral") as "accent" | "info" | "neutral";

export function OrganizationSettings({
  org,
  currentUserId,
  myRole,
  canManage,
  isOwner,
  members,
  invitations,
}: {
  org: { id: string; name: string; slug: string };
  currentUserId: string;
  myRole: string;
  canManage: boolean;
  isOwner: boolean;
  members: Member[];
  invitations: Invitation[];
}) {
  const router = useRouter();
  const assignable = ROLE_OPTIONS.filter((r) => isOwner || r.value !== "owner");

  async function changeRole(member: Member, role: Role) {
    const { error } = await authClient.organization.updateMemberRole({ memberId: member.id, role, organizationId: org.id });
    if (error) toast.error(error.message ?? "Could not change the role");
    else {
      toast.success(`${member.name || member.email} is now ${role}`);
      router.refresh();
    }
  }

  async function remove(member: Member) {
    if (!window.confirm(`Remove ${member.email} from ${org.name}?`)) return;
    const { error } = await authClient.organization.removeMember({ memberIdOrEmail: member.id, organizationId: org.id });
    if (error) toast.error(error.message ?? "Could not remove the member");
    else {
      toast.success("Member removed");
      router.refresh();
    }
  }

  async function leave() {
    if (!window.confirm(`Leave ${org.name}? You will lose access to its projects.`)) return;
    const { error } = await authClient.organization.leave({ organizationId: org.id });
    if (error) toast.error(error.message ?? "Could not leave the organization");
    else {
      router.push("/onboarding");
      router.refresh();
    }
  }

  async function cancelInvite(invitation: Invitation) {
    const { error } = await authClient.organization.cancelInvitation({ invitationId: invitation.id });
    if (error) toast.error(error.message ?? "Could not cancel the invitation");
    else {
      toast.success("Invitation cancelled");
      router.refresh();
    }
  }

  return (
    <div className="grid gap-5">
      <Panel>
        <PanelHeader
          title="Members"
          description={`${members.length} ${members.length === 1 ? "member" : "members"}. Your role: ${myRole}.`}
          actions={canManage ? <InviteButton orgId={org.id} roles={assignable} onInvited={() => router.refresh()} /> : null}
        />
        <ul className="divide-y divide-border">
          {members.map((m) => {
            const isMe = m.userId === currentUserId;
            const editable = canManage && !isMe && (isOwner || !m.role.includes("owner"));
            return (
              <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xs font-medium uppercase">
                  {(m.name || m.email).slice(0, 1)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {m.name || m.email}
                    {isMe ? <span className="ml-1.5 text-xs font-normal text-muted-foreground">(you)</span> : null}
                  </p>
                  <p className="truncate text-xs text-muted-foreground">
                    {m.email} · joined {formatRelative(m.createdAt)}
                  </p>
                </div>
                {editable ? (
                  <div className="w-32">
                    <Select
                      aria-label={`Role for ${m.email}`}
                      value={m.role}
                      onValueChange={(v) => changeRole(m, v as Role)}
                      options={assignable.map((r) => ({ value: r.value, label: r.label }))}
                    />
                  </div>
                ) : (
                  <Badge tone={roleTone(m.role)} className="capitalize">
                    {m.role}
                  </Badge>
                )}
                {editable || isMe ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${m.email}`}>
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {isMe ? (
                        <DropdownMenuItem onSelect={leave}>
                          <UserMinus /> Leave organization
                        </DropdownMenuItem>
                      ) : (
                        <DropdownMenuItem onSelect={() => remove(m)} className="text-error">
                          <Trash2 className="!text-error" /> Remove member
                        </DropdownMenuItem>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : null}
              </li>
            );
          })}
        </ul>
      </Panel>

      <Panel>
        <PanelHeader title="Pending invitations" description="Invitations expire after 48 hours." />
        {invitations.length === 0 ? (
          <EmptyState title="No pending invitations" className="py-8">
            {canManage ? "Invite teammates by email. They join with the role you choose." : "Owners and admins can invite teammates."}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border">
            {invitations.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">{i.email}</p>
                  <p className="text-xs text-muted-foreground">Expires {formatDateTime(i.expiresAt)}</p>
                </div>
                <Badge tone={roleTone(i.role)} className="capitalize">
                  {i.role}
                </Badge>
                {canManage ? (
                  <Button variant="ghost" size="sm" onClick={() => cancelInvite(i)}>
                    Cancel
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel>
        <PanelHeader title="Roles" description="Organization roles apply to every project in the organization." />
        <dl className="grid gap-px sm:grid-cols-2">
          {ROLE_OPTIONS.map((r) => (
            <div key={r.value} className="px-4 py-3">
              <dt className="text-sm font-medium">{r.label}</dt>
              <dd className="mt-0.5 text-xs text-muted-foreground">{r.description}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  );
}

function InviteButton({
  orgId,
  roles,
  onInvited,
}: {
  orgId: string;
  roles: typeof ROLE_OPTIONS;
  onInvited: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<Role>("member");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setEmail("");
          setError(null);
        }
      }}
    >
      <Button variant="primary" size="sm" onClick={() => setOpen(true)}>
        <MailPlus /> Invite
      </Button>
      <DialogContent title="Invite a member" description="They receive an email with a link to join.">
        <form
          className="grid gap-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setPending(true);
            setError(null);
            const { error } = await authClient.organization.inviteMember({ email: email.trim(), role, organizationId: orgId });
            setPending(false);
            if (error) {
              setError(error.message ?? "Could not send the invitation");
              return;
            }
            toast.success(`Invitation sent to ${email.trim()}`);
            setOpen(false);
            setEmail("");
            onInvited();
          }}
        >
          <Field label="Email" htmlFor="invite-email">
            <Input id="invite-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Role" htmlFor="invite-role" hint={roles.find((r) => r.value === role)?.description}>
            <Select id="invite-role" value={role} onValueChange={(v) => setRole(v as Role)} options={roles.map((r) => ({ value: r.value, label: r.label }))} />
          </Field>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" loading={pending} disabled={!email.trim()}>
              Send invitation
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}