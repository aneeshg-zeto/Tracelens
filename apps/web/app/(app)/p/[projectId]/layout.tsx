import { getProject } from "@/lib/project";

export default async function ProjectLayout({ children, params }: LayoutProps<"/p/[projectId]">) {
  const { projectId } = await params;
  await getProject(projectId);
  return children;
}
