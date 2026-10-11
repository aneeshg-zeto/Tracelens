import { Panel, Skeleton } from "@/components/ui/primitives";

export default function TracesLoading() {
  return (
    <div className="mx-auto max-w-7xl" aria-label="Loading traces">
      <Skeleton className="mb-2 h-6 w-28" />
      <Skeleton className="mb-5 h-4 w-64" />
      <Skeleton className="mb-3 h-8 w-full" />
      <Panel>
        {Array.from({ length: 10 }, (_, i) => (
          <div key={i} className="flex items-center gap-4 border-b border-border px-4 py-3 last:border-0">
            <Skeleton className="h-4 w-14" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-3.5 w-1/3" />
              <Skeleton className="h-3 w-1/5" />
            </div>
            <Skeleton className="h-3.5 w-14" />
            <Skeleton className="h-3.5 w-12" />
          </div>
        ))}
      </Panel>
    </div>
  );
}
