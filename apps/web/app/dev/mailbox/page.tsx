import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Logo } from "@/components/brand";
import { Badge, EmptyState, Panel } from "@/components/ui/primitives";
import { pool } from "@/lib/db";
import { env, smtpConfigured } from "@/lib/env";
import { formatDateTime } from "@/lib/utils";

export const metadata: Metadata = { title: "Development mailbox" };

type Message = {
  id: string;
  recipient: string;
  subject: string;
  body: string;
  kind: string;
  link: string | null;
  created_at: string;
};

export default async function DevMailboxPage() {
  if (env().TRACELENS_ENV === "production") notFound();
  const { rows } = await pool().query<Message>(
    "SELECT id, recipient, subject, body, kind, link, created_at FROM dev_mail_outbox ORDER BY created_at DESC LIMIT 50",
  );
  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <Logo />
      <h1 className="mt-8 text-lg font-semibold">Development mailbox</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {smtpConfigured()
          ? "SMTP is configured, so new emails are delivered for real. Older local messages are listed below."
          : "SMTP is not configured. Verification, password reset, and invitation emails are stored here instead of being sent. This page does not exist in production."}
      </p>
      <Panel className="mt-6 divide-y divide-border">
        {rows.length === 0 ? (
          <EmptyState title="No messages yet">Sign up or request a password reset to see emails here.</EmptyState>
        ) : (
          rows.map((m) => (
            <article key={m.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge tone="accent">{m.kind}</Badge>
                <span>to {m.recipient}</span>
                <span className="ml-auto font-mono">{formatDateTime(m.created_at)}</span>
              </div>
              <h2 className="mt-1.5 text-sm font-medium">{m.subject}</h2>
              {m.link ? (
                <a href={m.link} className="mt-1 block break-all font-mono text-xs text-accent hover:underline">
                  {m.link}
                </a>
              ) : null}
            </article>
          ))
        )}
      </Panel>
    </div>
  );
}
