import { SearchX } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { EmptyState, Panel } from "@/components/ui/primitives";

export default function AppNotFound() {
  return (
    <div className="mx-auto max-w-xl pt-10">
      <Panel>
        <EmptyState
          icon={<SearchX />}
          title="Nothing here"
          action={
            <Button asChild variant="secondary">
              <Link href="/projects">Back to projects</Link>
            </Button>
          }
        >
          This page does not exist, or it belongs to an organization you are not a member of. Switch organizations from
          the sidebar if you expected to see it.
        </EmptyState>
      </Panel>
    </div>
  );
}
