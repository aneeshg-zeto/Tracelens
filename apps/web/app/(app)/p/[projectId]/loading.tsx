import { Panel, Skeleton } from "@/components/ui/primitives";

export default function ProjectLoading() {
  return (
    <div className="mx-auto max-w-7xl space-y-4" aria-label="Loading">
      <div>
        <Skeleton className="mb-2 h-6 w-40" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Panel className="grid grid-cols-2 gap-4 p-4 lg:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-6 w-20" />
          </div>
        ))}
      </Panel>
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Skeleton className="h-60" />
        <Skeleton className="h-60" />
      </div>
    </div>
  );
}
