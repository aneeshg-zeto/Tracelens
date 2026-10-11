"use client";

import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, Mono, Panel } from "@/components/ui/primitives";

export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-xl pt-10">
      <Panel>
        <EmptyState
          icon={<TriangleAlert />}
          title="This page failed to load"
          action={
            <Button variant="secondary" onClick={reset}>
              Try again
            </Button>
          }
        >
          <p>The TraceLens API may be unavailable or returned an unexpected response.</p>
          {error.digest ? (
            <p className="mt-2">
              Reference <Mono>{error.digest}</Mono>
            </p>
          ) : null}
        </EmptyState>
      </Panel>
    </div>
  );
}
