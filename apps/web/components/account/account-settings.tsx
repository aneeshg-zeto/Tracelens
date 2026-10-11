"use client";

import { Laptop, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Alert, Badge, Panel, PanelHeader } from "@/components/ui/primitives";
import { authClient } from "@/lib/auth-client";
import { formatDateTime, formatRelative } from "@/lib/utils";

type SessionRow = {
  id: string;
  token: string;
  userAgent: string | null;
  ipAddress: string | null;
  createdAt: string;
  expiresAt: string;
};

function describeAgent(ua: string | null) {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Mac OS X/.test(ua) ? "macOS" : /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}

export function AccountSettings({
  user,
  currentSessionId,
  sessions,
  providers,
  googleAvailable,
}: {
  user: { name: string; email: string; emailVerified: boolean };
  currentSessionId: string;
  sessions: SessionRow[];
  providers: string[];
  googleAvailable: boolean;
}) {
  const router = useRouter();
  const hasPassword = providers.includes("credential");
  const hasGoogle = providers.includes("google");

  return (
    <div className="grid gap-5">
      <ProfileForm user={user} onSaved={() => router.refresh()} />

      <Panel>
        <PanelHeader title="Sign-in methods" />
        <ul className="divide-y divide-border">
          <li className="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <p className="text-sm font-medium">Email and password</p>
              <p className="text-xs text-muted-foreground">{hasPassword ? "Enabled" : "Not set up for this account"}</p>
            </div>
            {hasPassword ? <Badge tone="ok">Active</Badge> : <Badge>Unavailable</Badge>}
          </li>
          <li className="flex items-center justify-between gap-3 px-4 py-3">
            <div>
              <p className="text-sm font-medium">Google</p>
              <p className="text-xs text-muted-foreground">
                {hasGoogle ? "Linked" : googleAvailable ? "Link your Google account to sign in with it" : "Google sign-in is not configured on this server"}
              </p>
            </div>
            {hasGoogle ? (
              <Badge tone="ok">Linked</Badge>
            ) : googleAvailable ? (
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  const { error } = await authClient.linkSocial({ provider: "google", callbackURL: "/settings/account" });
                  if (error) toast.error(error.message ?? "Could not link Google");
                }}
              >
                Link Google
              </Button>
            ) : null}
          </li>
        </ul>
      </Panel>

      {hasPassword ? <PasswordForm /> : null}

      <Panel>
        <PanelHeader
          title="Active sessions"
          description="Revoke any session you do not recognize."
          actions={
            sessions.length > 1 ? (
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  const { error } = await authClient.revokeOtherSessions();
                  if (error) toast.error(error.message ?? "Could not revoke sessions");
                  else {
                    toast.success("Other sessions revoked");
                    router.refresh();
                  }
                }}
              >
                Revoke all others
              </Button>
            ) : null
          }
        />
        <ul className="divide-y divide-border">
          {sessions.map((s) => {
            const current = s.id === currentSessionId;
            return (
              <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <Laptop className="size-4 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm">
                    {describeAgent(s.userAgent)}
                    {current ? (
                      <Badge tone="accent" className="ml-2">
                        This device
                      </Badge>
                    ) : null}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {s.ipAddress && !/^[0:.]*$/.test(s.ipAddress) ? `${s.ipAddress} · ` : ""}signed in {formatRelative(s.createdAt)} · expires {formatDateTime(s.expiresAt)}
                  </p>
                </div>
                {!current ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      const { error } = await authClient.revokeSession({ token: s.token });
                      if (error) toast.error(error.message ?? "Could not revoke the session");
                      else {
                        toast.success("Session revoked");
                        router.refresh();
                      }
                    }}
                  >
                    Revoke
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      </Panel>
    </div>
  );
}

function ProfileForm({ user, onSaved }: { user: { name: string; email: string; emailVerified: boolean }; onSaved: () => void }) {
  const [name, setName] = React.useState(user.name);
  const [pending, setPending] = React.useState(false);
  return (
    <Panel>
      <PanelHeader title="Profile" />
      <form
        className="grid gap-3 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setPending(true);
          const { error } = await authClient.updateUser({ name: name.trim() });
          setPending(false);
          if (error) toast.error(error.message ?? "Could not save");
          else {
            toast.success("Profile saved");
            onSaved();
          }
        }}
      >
        <div className="grid items-start gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="profile-name">
            <Input id="profile-name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Email" htmlFor="profile-email" hint={user.emailVerified ? "Verified" : "Not verified"}>
            <Input id="profile-email" value={user.email} readOnly disabled />
          </Field>
        </div>
        <div>
          <Button type="submit" variant="secondary" loading={pending} disabled={!name.trim() || name.trim() === user.name}>
            Save
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function PasswordForm() {
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [revokeOthers, setRevokeOthers] = React.useState(true);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <Panel>
      <PanelHeader title="Change password" />
      <form
        className="grid gap-3 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setPending(true);
          setError(null);
          const { error } = await authClient.changePassword({ currentPassword: current, newPassword: next, revokeOtherSessions: revokeOthers });
          setPending(false);
          if (error) {
            setError(error.message ?? "Could not change the password");
            return;
          }
          setCurrent("");
          setNext("");
          toast.success("Password changed");
        }}
      >
        <div className="grid items-start gap-3 sm:grid-cols-2">
          <Field label="Current password" htmlFor="current-password">
            <Input id="current-password" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New password" htmlFor="new-password" hint="At least 10 characters.">
            <Input id="new-password" type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" className="accent-[var(--accent)]" checked={revokeOthers} onChange={(e) => setRevokeOthers(e.target.checked)} />
          Sign out of other sessions
        </label>
        {error ? <Alert tone="error">{error}</Alert> : null}
        <div>
          <Button type="submit" variant="secondary" loading={pending} disabled={!current || next.length < 10}>
            <ShieldCheck /> Change password
          </Button>
        </div>
      </form>
    </Panel>
  );
}
