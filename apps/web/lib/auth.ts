import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { organization } from "better-auth/plugins";
import { recordAudit } from "@/lib/audit";
import { ac, roles } from "@/lib/auth/permissions";
import { pool } from "@/lib/db";
import { env, googleConfigured } from "@/lib/env";
import { sendMail } from "@/lib/mail";

const e = env();

const trustedOrigins = [
  e.BETTER_AUTH_URL,
  ...(e.BETTER_AUTH_TRUSTED_ORIGINS?.split(",").map((o) => o.trim()).filter(Boolean) ?? []),
];

export const auth = betterAuth({
  appName: "TraceLens",
  baseURL: e.BETTER_AUTH_URL,
  secret: e.BETTER_AUTH_SECRET,
  database: pool(),
  trustedOrigins,
  emailAndPassword: {
    enabled: true,
    requireEmailVerification: true,
    minPasswordLength: 10,
    maxPasswordLength: 128,
    revokeSessionsOnPasswordReset: true,
    resetPasswordTokenExpiresIn: 60 * 30,
    sendResetPassword: async ({ user, url }) => {
      await sendMail({
        to: user.email,
        subject: "Reset your TraceLens password",
        text: `Someone requested a password reset for your TraceLens account.\n\nReset it here (valid for 30 minutes):\n${url}\n\nIf you did not request this, ignore this email.`,
        kind: "reset-password",
        link: url,
      });
    },
  },
  emailVerification: {
    sendOnSignUp: true,
    sendOnSignIn: true,
    autoSignInAfterVerification: true,
    expiresIn: 60 * 60 * 24,
    sendVerificationEmail: async ({ user, url }) => {
      await sendMail({
        to: user.email,
        subject: "Verify your TraceLens email",
        text: `Confirm your email address to finish creating your TraceLens account:\n${url}\n\nThis link expires in 24 hours.`,
        kind: "verify-email",
        link: url,
      });
    },
  },
  socialProviders: googleConfigured()
    ? {
        google: {
          clientId: e.GOOGLE_CLIENT_ID!,
          clientSecret: e.GOOGLE_CLIENT_SECRET!,
          prompt: "select_account",
        },
      }
    : {},
  account: {
    accountLinking: {
      enabled: true,
      trustedProviders: ["google"],
    },
  },
  session: {
    expiresIn: 60 * 60 * 24 * 7,
    updateAge: 60 * 60 * 24,
  },
  databaseHooks: {
    session: {
      create: {
        // New sessions start in the user's oldest organization so returning
        // users land in their workspace instead of onboarding.
        before: async (session) => {
          const { rows } = await pool().query<{ organizationId: string }>(
            `SELECT "organizationId" FROM member WHERE "userId" = $1 ORDER BY "createdAt" ASC LIMIT 1`,
            [session.userId],
          );
          return { data: { ...session, activeOrganizationId: rows[0]?.organizationId ?? null } };
        },
      },
    },
  },
  rateLimit: {
    enabled: e.TRACELENS_ENV !== "test",
    storage: "database",
    window: 60,
    max: 100,
  },
  advanced: {
    useSecureCookies: e.BETTER_AUTH_URL.startsWith("https://"),
  },
  plugins: [
    organization({
      ac,
      roles,
      creatorRole: "owner",
      allowUserToCreateOrganization: true,
      requireEmailVerificationOnInvitation: true,
      invitationExpiresIn: 60 * 60 * 48,
      sendInvitationEmail: async (data) => {
        const link = `${e.BETTER_AUTH_URL}/accept-invitation/${data.id}`;
        await sendMail({
          to: data.email,
          subject: `Join ${data.organization.name} on TraceLens`,
          text: `${data.inviter.user.name} invited you to the ${data.organization.name} organization on TraceLens as ${data.role}.\n\nAccept the invitation:\n${link}\n\nThe invitation expires in 48 hours.`,
          kind: "invitation",
          link,
        });
      },
      organizationHooks: {
        afterCreateOrganization: async ({ organization: org, user }) => {
          await recordAudit({
            organizationId: org.id,
            actorUserId: user.id,
            action: "organization.created",
            targetType: "organization",
            targetId: org.id,
          });
        },
        afterAddMember: async ({ member, organization: org }) => {
          await recordAudit({
            organizationId: org.id,
            actorUserId: null,
            action: "member.added",
            targetType: "member",
            targetId: member.id,
            metadata: { userId: member.userId, role: member.role },
          });
        },
        afterRemoveMember: async ({ member, organization: org }) => {
          await recordAudit({
            organizationId: org.id,
            actorUserId: null,
            action: "member.removed",
            targetType: "member",
            targetId: member.id,
            metadata: { userId: member.userId },
          });
        },
        afterUpdateMemberRole: async ({ member, previousRole, organization: org }) => {
          await recordAudit({
            organizationId: org.id,
            actorUserId: null,
            action: "member.role_changed",
            targetType: "member",
            targetId: member.id,
            metadata: { userId: member.userId, previousRole, newRole: member.role },
          });
        },
        afterCreateInvitation: async ({ invitation, inviter, organization: org }) => {
          await recordAudit({
            organizationId: org.id,
            actorUserId: inviter.id,
            action: "invitation.created",
            targetType: "invitation",
            targetId: invitation.id,
            metadata: { role: invitation.role },
          });
        },
        afterAcceptInvitation: async ({ invitation, user, organization: org }) => {
          await recordAudit({
            organizationId: org.id,
            actorUserId: user.id,
            action: "invitation.accepted",
            targetType: "invitation",
            targetId: invitation.id,
          });
        },
      },
    }),
    nextCookies(),
  ],
});

export type Session = typeof auth.$Infer.Session;
