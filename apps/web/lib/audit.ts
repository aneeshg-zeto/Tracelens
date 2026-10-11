import { pool } from "@/lib/db";

export type AuditInput = {
  organizationId: string;
  actorUserId: string | null;
  action: string;
  targetType: string;
  targetId: string | null;
  metadata?: Record<string, unknown>;
};

/**
 * Records security-sensitive organization events raised inside Better Auth
 * (membership, invitations, organization lifecycle). Project-level events are
 * written by the FastAPI backend into the same table.
 */
export async function recordAudit(input: AuditInput): Promise<void> {
  try {
    await pool().query(
      `INSERT INTO audit_events (organization_id, actor_user_id, action, target_type, target_id, metadata)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
      [
        input.organizationId,
        input.actorUserId,
        input.action,
        input.targetType,
        input.targetId,
        JSON.stringify(input.metadata ?? {}),
      ],
    );
  } catch (error) {
    console.error("[tracelens] failed to record audit event", input.action, error);
  }
}
