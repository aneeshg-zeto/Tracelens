import { z } from "zod";

const optional = z
  .string()
  .optional()
  .transform((v) => (v && v.trim() !== "" ? v.trim() : undefined));

const schema = z.object({
  TRACELENS_ENV: z.enum(["development", "test", "production"]).default("development"),
  DATABASE_URL: z.string().min(1, "DATABASE_URL is required"),
  BETTER_AUTH_SECRET: z.string().min(32, "BETTER_AUTH_SECRET must be at least 32 characters"),
  BETTER_AUTH_URL: z.url(),
  BETTER_AUTH_TRUSTED_ORIGINS: optional,
  GOOGLE_CLIENT_ID: optional,
  GOOGLE_CLIENT_SECRET: optional,
  TRACELENS_API_URL: z.url().default("http://localhost:8000"),
  INTERNAL_JWT_SECRET: z.string().min(32, "INTERNAL_JWT_SECRET must be at least 32 characters"),
  SMTP_HOST: optional,
  SMTP_PORT: optional,
  SMTP_USER: optional,
  SMTP_PASSWORD: optional,
  SMTP_FROM: optional,
});

export type ServerEnv = z.infer<typeof schema>;

// `next build` imports route modules (including the auth handler) without
// executing requests. These inert values let an image build without runtime
// secrets; they are never used to sign or connect, and runtime validation
// still requires the real variables.
const BUILD_PHASE_PLACEHOLDERS = {
  DATABASE_URL: "postgresql://build:build@127.0.0.1:1/build",
  BETTER_AUTH_SECRET: "build-phase-placeholder-never-used-at-runtime",
  BETTER_AUTH_URL: "http://localhost:3000",
  INTERNAL_JWT_SECRET: "build-phase-placeholder-never-used-at-runtime",
};

let cached: ServerEnv | null = null;

export function env(): ServerEnv {
  if (cached) return cached;
  const source =
    process.env.NEXT_PHASE === "phase-production-build"
      ? { ...BUILD_PHASE_PLACEHOLDERS, ...process.env }
      : process.env;
  const parsed = schema.safeParse(source);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((i) => `  - ${i.path.join(".")}: ${i.message}`)
      .join("\n");
    throw new Error(
      `TraceLens web is misconfigured. Fix these environment variables (see .env.example):\n${issues}`,
    );
  }
  cached = parsed.data;
  return cached;
}

export function isDevelopment(): boolean {
  return env().TRACELENS_ENV === "development";
}

export function googleConfigured(): boolean {
  const e = env();
  return Boolean(e.GOOGLE_CLIENT_ID && e.GOOGLE_CLIENT_SECRET);
}

export function smtpConfigured(): boolean {
  const e = env();
  return Boolean(e.SMTP_HOST && e.SMTP_FROM);
}
