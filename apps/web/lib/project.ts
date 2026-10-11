import { cache } from "react";
import { apiOrNotFound } from "@/lib/api";
import type { Permissions, ProjectDetail } from "@/lib/types";

/** One fetch per request, shared by the project layout and its pages. */
export const getProject = cache((projectId: string) =>
  apiOrNotFound<ProjectDetail>(`/projects/${encodeURIComponent(projectId)}`),
);

export function can(permissions: Permissions, resource: string, action: string): boolean {
  return (permissions[resource] ?? []).includes(action);
}

export const enc = encodeURIComponent;
