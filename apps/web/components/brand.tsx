import Link from "next/link";
import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-5", className)} aria-hidden fill="none">
      <rect x="2.5" y="4" width="13" height="3" rx="1" fill="currentColor" opacity="0.45" />
      <rect x="6.5" y="10.5" width="9" height="3" rx="1" fill="currentColor" opacity="0.7" />
      <rect x="10.5" y="17" width="11" height="3" rx="1" className="fill-accent" />
      <path d="M4 7v5h2.5M8 13.5V18.5h2.5" stroke="currentColor" strokeWidth="1.2" opacity="0.45" />
    </svg>
  );
}

export function Logo({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn("inline-flex items-center gap-2 text-foreground", className)}>
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-[-0.02em]">TraceLens</span>
    </Link>
  );
}
