import Link from "next/link";
import { cn } from "@/lib/utils";

/** URL-driven segmented control; each option is a link so state survives reloads and sharing. */
export function SegmentedLinks({
  options,
  value,
  label,
}: {
  options: { value: string; label: string; href: string }[];
  value: string;
  label: string;
}) {
  return (
    <nav aria-label={label} className="inline-flex rounded-md border border-border bg-surface p-0.5">
      {options.map((o) => (
        <Link
          key={o.value}
          href={o.href}
          scroll={false}
          aria-current={o.value === value ? "page" : undefined}
          className={cn(
            "rounded-[4px] px-2.5 py-1 font-mono text-xs text-muted-foreground transition-colors hover:text-foreground",
            o.value === value && "bg-muted text-foreground shadow-[inset_0_-2px_0_var(--accent)]",
          )}
        >
          {o.label}
        </Link>
      ))}
    </nav>
  );
}
