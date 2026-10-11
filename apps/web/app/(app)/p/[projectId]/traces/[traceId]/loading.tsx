import { Panel, Skeleton } from "@/components/ui/primitives";

export default function TraceLoading() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-4" aria-label="Loading trace">
      <div>
        <Skeleton className="mb-3 h-3 w-16" />
        <Skeleton className="mb-2 h-6 w-72" />
        <Skeleton className="h-4 w-56" />
      </div>
      <Skeleton className="h-16 w-full" />
      <div className="grid gap-4 xl:grid-cols-[1fr_440px]">
        <Panel className="space-y-0">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="grid grid-cols-[40%_1fr] items-center gap-3 border-b border-border px-4 py-2 last:border-0">
              <Skeleton className="h-3.5" style={{ width: `${70 - (i % 4) * 10}%`, marginLeft: (i % 4) * 14 }} />
              <Skeleton className="h-3" style={{ width: `${20 + ((i * 17) % 50)}%`, marginLeft: `${(i * 7) % 40}%` }} />
            </div>
          ))}
        </Panel>
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}
