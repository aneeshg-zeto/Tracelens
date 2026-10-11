import nodemailer, { type Transporter } from "nodemailer";
import { env, smtpConfigured } from "@/lib/env";
import { pool } from "@/lib/db";

export type MailMessage = {
  to: string;
  subject: string;
  text: string;
  kind: "verify-email" | "reset-password" | "invitation";
  link: string;
};

export class MailNotConfiguredError extends Error {
  constructor() {
    super(
      "Email delivery is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and SMTP_FROM.",
    );
    this.name = "MailNotConfiguredError";
  }
}

let transporter: Transporter | null = null;

function smtp(): Transporter {
  if (transporter) return transporter;
  const e = env();
  const port = Number(e.SMTP_PORT ?? "587");
  transporter = nodemailer.createTransport({
    host: e.SMTP_HOST,
    port,
    secure: port === 465,
    auth: e.SMTP_USER ? { user: e.SMTP_USER, pass: e.SMTP_PASSWORD ?? "" } : undefined,
  });
  return transporter;
}

/**
 * Sends an auth email through SMTP. Without SMTP, development and test
 * environments write the message to the dev_mail_outbox table (readable at
 * /dev/mailbox). Production without SMTP fails loudly instead of pretending the
 * message was delivered.
 */
export async function sendMail(message: MailMessage): Promise<void> {
  const e = env();
  if (smtpConfigured()) {
    await smtp().sendMail({
      from: e.SMTP_FROM,
      to: message.to,
      subject: message.subject,
      text: message.text,
    });
    return;
  }
  if (e.TRACELENS_ENV === "production") {
    throw new MailNotConfiguredError();
  }
  await pool().query(
    `INSERT INTO dev_mail_outbox (recipient, subject, body, kind, link) VALUES ($1, $2, $3, $4, $5)`,
    [message.to, message.subject, message.text, message.kind, message.link],
  );
  console.info(
    `[tracelens] SMTP not configured; ${message.kind} email for ${message.to} stored in dev mailbox (/dev/mailbox).`,
  );
}
