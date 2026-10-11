"use client";

import { useSearchParams } from "next/navigation";
import * as React from "react";

/**
 * Selected span lives in `?span=` so links are shareable. Uses the History API
 * directly, which Next keeps in sync with useSearchParams without a server
 * round trip.
 */
export function useSpanSelection(): [string | null, (spanId: string | null) => void] {
  const params = useSearchParams();
  const select = React.useCallback((spanId: string | null) => {
    const next = new URLSearchParams(window.location.search);
    if (spanId) next.set("span", spanId);
    else next.delete("span");
    const qs = next.toString();
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, []);
  return [params.get("span"), select];
}
