"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { Alert } from "@/components/ui/primitives";
import { authClient } from "@/lib/auth-client";

const email = z.email("Enter a valid email address");
const password = z
  .string()
  .min(10, "Use at least 10 characters")
  .max(128, "Use at most 128 characters");

function safeNext(next: string | undefined, fallback: string) {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

export function AuthHeading({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">{title}</h1>
      {children ? <p className="mt-1.5 text-sm text-muted-foreground">{children}</p> : null}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-4">
      <path fill="#4285F4" d="M22.6 12.2c0-.8-.1-1.5-.2-2.2H12v4.2h5.9a5 5 0 0 1-2.2 3.3v2.7h3.6c2-1.9 3.3-4.7 3.3-8Z" />
      <path fill="#34A853" d="M12 23c3 0 5.5-1 7.3-2.7l-3.6-2.8c-1 .7-2.2 1.1-3.7 1.1-2.9 0-5.3-1.9-6.2-4.5H2.1v2.8A11 11 0 0 0 12 23Z" />
      <path fill="#FBBC05" d="M5.8 14.1a6.6 6.6 0 0 1 0-4.2V7.1H2.1a11 11 0 0 0 0 9.8l3.7-2.8Z" />
      <path fill="#EA4335" d="M12 5.4c1.6 0 3.1.6 4.2 1.7l3.2-3.2A11 11 0 0 0 2.1 7.1l3.7 2.8C6.7 7.3 9.1 5.4 12 5.4Z" />
    </svg>
  );
}

function GoogleButton({ next }: { next: string }) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <div className="grid gap-2">
      <Button
        type="button"
        variant="secondary"
        size="lg"
        loading={loading}
        onClick={async () => {
          setLoading(true);
          setError(null);
          const { error } = await authClient.signIn.social({ provider: "google", callbackURL: next });
          if (error) {
            setError(error.message ?? "Google sign-in failed");
            setLoading(false);
          }
        }}
      >
        {!loading ? <GoogleIcon /> : null}
        Continue with Google
      </Button>
      {error ? <p className="text-xs text-error">{error}</p> : null}
    </div>
  );
}

function Divider() {
  return (
    <div className="my-5 flex items-center gap-3 text-[11px] text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      or with email
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

function DevMailboxHint({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <Alert tone="info" className="mt-4">
      SMTP is not configured, so emails are stored locally. Open the{" "}
      <Link href="/dev/mailbox" className="font-medium text-foreground underline">
        development mailbox
      </Link>
      .
    </Alert>
  );
}

/* Sign in ----------------------------------------------------------------- */

const signInSchema = z.object({ email, password: z.string().min(1, "Enter your password") });

export function SignInForm({ google, next, devMailbox }: { google: boolean; next?: string; devMailbox: boolean }) {
  const router = useRouter();
  const target = safeNext(next, "/projects");
  const [error, setError] = React.useState<{ message: string; unverified?: boolean } | null>(null);
  const form = useForm<z.infer<typeof signInSchema>>({ resolver: zodResolver(signInSchema) });
  const { errors, isSubmitting } = form.formState;

  return (
    <>
      {google ? (
        <>
          <GoogleButton next={target} />
          <Divider />
        </>
      ) : null}
      <form
        noValidate
        className="grid gap-4"
        onSubmit={form.handleSubmit(async (values) => {
          setError(null);
          const { error } = await authClient.signIn.email({ ...values, callbackURL: target });
          if (error) {
            const unverified = error.code === "EMAIL_NOT_VERIFIED" || error.status === 403;
            setError({
              unverified,
              message: unverified
                ? "Verify your email first. We just sent a new verification link."
                : (error.message ?? "Sign-in failed"),
            });
            return;
          }
          router.push(target);
          router.refresh();
        })}
      >
        <Field label="Email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            {...form.register("password")}
          />
        </Field>
        {error ? <Alert tone={error.unverified ? "warn" : "error"}>{error.message}</Alert> : null}
        <Button type="submit" variant="primary" size="lg" loading={isSubmitting}>
          Sign in
        </Button>
      </form>
      {error?.unverified ? <DevMailboxHint show={devMailbox} /> : null}
      <div className="mt-5 flex justify-between text-sm">
        <Link href="/forgot-password" className="text-muted-foreground hover:text-foreground">
          Forgot password?
        </Link>
        <Link href={next ? `/sign-up?next=${encodeURIComponent(next)}` : "/sign-up"} className="text-accent hover:underline">
          Create an account
        </Link>
      </div>
    </>
  );
}

/* Sign up ----------------------------------------------------------------- */

const signUpSchema = z.object({
  name: z.string().trim().min(1, "Enter your name").max(80),
  email,
  password,
});

export function SignUpForm({ google, next, devMailbox }: { google: boolean; next?: string; devMailbox: boolean }) {
  const target = safeNext(next, "/onboarding");
  const [sentTo, setSentTo] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const form = useForm<z.infer<typeof signUpSchema>>({ resolver: zodResolver(signUpSchema) });
  const { errors, isSubmitting } = form.formState;

  if (sentTo) {
    return (
      <div>
        <div className="mb-4 grid size-9 place-items-center rounded-md border border-border bg-surface-2 text-accent">
          <MailCheck className="size-4" />
        </div>
        <AuthHeading title="Check your email">
          We sent a verification link to <span className="font-medium text-foreground">{sentTo}</span>. Open it to
          finish creating your account. The link expires in 24 hours.
        </AuthHeading>
        <DevMailboxHint show={devMailbox} />
        <ResendVerification email={sentTo} callbackURL={target} />
      </div>
    );
  }

  return (
    <>
      <AuthHeading title="Create your account">Trace, debug, and evaluate your AI agents.</AuthHeading>
      {google ? (
        <>
          <GoogleButton next={target} />
          <Divider />
        </>
      ) : null}
      <form
        noValidate
        className="grid gap-4"
        onSubmit={form.handleSubmit(async (values) => {
          setError(null);
          const { error } = await authClient.signUp.email({ ...values, callbackURL: target });
          if (error) {
            setError(error.message ?? "Could not create the account");
            return;
          }
          setSentTo(values.email);
        })}
      >
        <Field label="Name" htmlFor="name" error={errors.name?.message}>
          <Input id="name" autoComplete="name" aria-invalid={!!errors.name} {...form.register("name")} />
        </Field>
        <Field label="Work email" htmlFor="email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 10 characters." error={errors.password?.message}>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            aria-invalid={!!errors.password}
            {...form.register("password")}
          />
        </Field>
        {error ? <Alert tone="error">{error}</Alert> : null}
        <Button type="submit" variant="primary" size="lg" loading={isSubmitting}>
          Create account
        </Button>
      </form>
      <p className="mt-5 text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href={next ? `/sign-in?next=${encodeURIComponent(next)}` : "/sign-in"} className="text-accent hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}

export function ResendVerification({ email: initial, callbackURL = "/onboarding" }: { email?: string; callbackURL?: string }) {
  const [value, setValue] = React.useState(initial ?? "");
  const [state, setState] = React.useState<"idle" | "sending" | "sent" | "error">("idle");
  return (
    <form
      className="mt-6 grid gap-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setState("sending");
        const { error } = await authClient.sendVerificationEmail({ email: value, callbackURL });
        setState(error ? "error" : "sent");
      }}
    >
      {!initial ? (
        <Field label="Email" htmlFor="resend-email">
          <Input id="resend-email" type="email" required value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
      ) : null}
      <Button type="submit" variant="secondary" loading={state === "sending"} disabled={!value}>
        Resend verification email
      </Button>
      {state === "sent" ? <p className="text-xs text-ok">Sent. Check your inbox.</p> : null}
      {state === "error" ? <p className="text-xs text-error">Could not send the email. Try again shortly.</p> : null}
    </form>
  );
}

/* Password reset ---------------------------------------------------------- */

export function ForgotPasswordForm({ devMailbox }: { devMailbox: boolean }) {
  const [sent, setSent] = React.useState(false);
  const form = useForm<{ email: string }>({ resolver: zodResolver(z.object({ email })) });
  const { errors, isSubmitting } = form.formState;
  if (sent) {
    return (
      <>
        <Alert tone="ok" title="Check your email">
          If an account exists for that address, we sent a reset link. It expires in 30 minutes.
        </Alert>
        <DevMailboxHint show={devMailbox} />
      </>
    );
  }
  return (
    <form
      noValidate
      className="grid gap-4"
      onSubmit={form.handleSubmit(async ({ email }) => {
        await authClient.requestPasswordReset({ email, redirectTo: "/reset-password" });
        setSent(true);
      })}
    >
      <Field label="Email" htmlFor="email" error={errors.email?.message}>
        <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...form.register("email")} />
      </Field>
      <Button type="submit" variant="primary" size="lg" loading={isSubmitting}>
        Send reset link
      </Button>
    </form>
  );
}

const resetSchema = z
  .object({ password, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });

export function ResetPasswordForm({ token }: { token: string }) {
  const router = useRouter();
  const [error, setError] = React.useState<string | null>(null);
  const form = useForm<z.infer<typeof resetSchema>>({ resolver: zodResolver(resetSchema) });
  const { errors, isSubmitting } = form.formState;
  return (
    <form
      noValidate
      className="grid gap-4"
      onSubmit={form.handleSubmit(async ({ password }) => {
        setError(null);
        const { error } = await authClient.resetPassword({ newPassword: password, token });
        if (error) {
          setError(error.message ?? "This reset link is invalid or has expired.");
          return;
        }
        router.push("/sign-in?reset=1");
      })}
    >
      <Field label="New password" htmlFor="password" hint="At least 10 characters." error={errors.password?.message}>
        <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!errors.password} {...form.register("password")} />
      </Field>
      <Field label="Confirm password" htmlFor="confirm" error={errors.confirm?.message}>
        <Input id="confirm" type="password" autoComplete="new-password" aria-invalid={!!errors.confirm} {...form.register("confirm")} />
      </Field>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Button type="submit" variant="primary" size="lg" loading={isSubmitting}>
        Set new password
      </Button>
      <p className="text-xs text-muted-foreground">Other signed-in sessions are signed out when you reset.</p>
    </form>
  );
}
