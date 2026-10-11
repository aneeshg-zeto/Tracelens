import { createAccessControl } from "better-auth/plugins/access";
import {
  adminAc,
  defaultStatements,
  memberAc,
  ownerAc,
} from "better-auth/plugins/organization/access";

/**
 * TraceLens permission statements. Organization, member, and invitation
 * actions are enforced by Better Auth. Project-level resources are enforced by
 * the FastAPI backend, which mirrors this matrix in app/core/permissions.py.
 * Keep the two in sync.
 */
export const statement = {
  ...defaultStatements,
  project: ["create", "update", "delete"],
  apiKey: ["create", "revoke"],
  trace: ["read", "ingest", "delete"],
  evaluation: ["read", "create", "run"],
  prompt: ["read", "create", "publish"],
  integration: ["read", "update"],
  audit: ["read"],
  investigation: ["read", "run"],
} as const;

export const ac = createAccessControl(statement);

export const owner = ac.newRole({
  ...ownerAc.statements,
  project: ["create", "update", "delete"],
  apiKey: ["create", "revoke"],
  trace: ["read", "ingest", "delete"],
  evaluation: ["read", "create", "run"],
  prompt: ["read", "create", "publish"],
  integration: ["read", "update"],
  audit: ["read"],
  investigation: ["read", "run"],
});

export const admin = ac.newRole({
  ...adminAc.statements,
  project: ["create", "update"],
  apiKey: ["create", "revoke"],
  trace: ["read", "ingest", "delete"],
  evaluation: ["read", "create", "run"],
  prompt: ["read", "create", "publish"],
  integration: ["read", "update"],
  audit: ["read"],
  investigation: ["read", "run"],
});

export const member = ac.newRole({
  ...memberAc.statements,
  trace: ["read", "ingest"],
  evaluation: ["read", "create", "run"],
  prompt: ["read", "create"],
  integration: ["read"],
  investigation: ["read", "run"],
});

export const viewer = ac.newRole({
  ...memberAc.statements,
  trace: ["read"],
  evaluation: ["read"],
  prompt: ["read"],
  integration: ["read"],
  investigation: ["read"],
});

export const roles = { owner, admin, member, viewer };

export type Role = keyof typeof roles;
export const ROLE_NAMES: Role[] = ["owner", "admin", "member", "viewer"];

type Statement = typeof statement;
type Resource = keyof Statement;

const matrix: Record<Role, Partial<Record<Resource, readonly string[]>>> = {
  owner: owner.statements,
  admin: admin.statements,
  member: member.statements,
  viewer: viewer.statements,
};

/**
 * Pure helper for hiding UI affordances. Never use this as the authorization
 * boundary; the server (Better Auth or FastAPI) re-checks every action.
 */
export function can<R extends Resource>(
  role: string | null | undefined,
  resource: R,
  action: Statement[R][number],
): boolean {
  if (!role) return false;
  return role
    .split(",")
    .map((r) => r.trim())
    .some((r) => {
      const allowed = matrix[r as Role]?.[resource];
      return Boolean(allowed && (allowed as readonly string[]).includes(action));
    });
}
