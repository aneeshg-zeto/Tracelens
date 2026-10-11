"use client";

import {
  Activity,
  Blocks,
  Building2,
  Check,
  ChevronsUpDown,
  FlaskConical,
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  NotebookPen,
  Plus,
  ScrollText,
  Settings,
  Sun,
  UserRound,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import * as React from "react";
import { toast } from "sonner";
import { Logo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/overlays";
import { Alert } from "@/components/ui/primitives";
import { authClient } from "@/lib/auth-client";
import type { Permissions } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  user: { name: string; email: string; image: string | null };
  organizations: { id: string; name: string }[];
  activeOrg: { id: string; name: string };
  role: string;
  permissions: Permissions;
  projects: { id: string; name: string }[];
};

type NavItem = { href: string; label: string; icon: React.ComponentType<{ className?: string }>; exact?: boolean };

export function AppSidebar(props: Props) {
  const [open, setOpen] = React.useState(false);
  const pathname = usePathname();
  const [openedAt, setOpenedAt] = React.useState(pathname);
  if (openedAt !== pathname) {
    setOpenedAt(pathname);
    setOpen(false);
  }

  return (
    <>
      <div className="sticky top-0 z-30 flex h-12 items-center justify-between border-b border-border bg-background/90 px-4 backdrop-blur lg:hidden">
        <Logo href="/projects" />
        <Button variant="ghost" size="icon-sm" aria-label={open ? "Close navigation" : "Open navigation"} onClick={() => setOpen((v) => !v)}>
          {open ? <X /> : <Menu />}
        </Button>
      </div>
      {open ? <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} aria-hidden /> : null}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[264px] flex-col border-r border-border bg-surface transition-transform lg:sticky lg:top-0 lg:z-auto lg:h-dvh lg:w-auto lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <SidebarBody {...props} />
      </aside>
    </>
  );
}

function SidebarBody({ user, organizations, activeOrg, role, permissions, projects }: Props) {
  const params = useParams<{ projectId?: string }>();
  const pathname = usePathname();
  const projectId = params.projectId;
  const project = projects.find((p) => p.id === projectId);

  const projectNav: NavItem[] = projectId
    ? [
        { href: `/p/${projectId}`, label: "Overview", icon: LayoutDashboard, exact: true },
        { href: `/p/${projectId}/traces`, label: "Traces", icon: Activity },
        { href: `/p/${projectId}/evaluations`, label: "Evaluations", icon: FlaskConical },
        { href: `/p/${projectId}/prompts`, label: "Prompts", icon: NotebookPen },
        { href: `/p/${projectId}/integrations`, label: "Integrations", icon: Blocks },
        { href: `/p/${projectId}/settings`, label: "Project settings", icon: Settings },
      ]
    : [];

  const orgNav: NavItem[] = [
    { href: "/projects", label: "Projects", icon: FolderKanban, exact: true },
    { href: "/settings/organization", label: "Members", icon: Users },
    ...((permissions.audit ?? []).includes("read") ? [{ href: "/settings/audit", label: "Audit log", icon: ScrollText }] : []),
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="hidden h-12 items-center px-4 lg:flex">
        <Logo href="/projects" />
      </div>
      <div className="px-2 pt-2 lg:pt-0">
        <OrgSwitcher organizations={organizations} activeOrg={activeOrg} role={role} />
      </div>

      <nav className="mt-3 min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Main">
        {projectId ? (
          <div className="mb-4">
            <ProjectSwitcher projects={projects} current={project} />
            <ul className="mt-1 grid gap-px">
              {projectNav.map((item) => (
                <NavLink key={item.href} item={item} pathname={pathname} />
              ))}
            </ul>
          </div>
        ) : null}
        <p className="px-2 pb-1 text-[11px] font-medium text-muted-foreground">Organization</p>
        <ul className="grid gap-px">
          {orgNav.map((item) => (
            <NavLink key={item.href} item={item} pathname={pathname} />
          ))}
        </ul>
        {!projectId && projects.length > 0 ? (
          <>
            <p className="mt-4 px-2 pb-1 text-[11px] font-medium text-muted-foreground">Recent projects</p>
            <ul className="grid gap-px">
              {projects.slice(0, 8).map((p) => (
                <li key={p.id}>
                  <Link
                    href={`/p/${p.id}`}
                    className="block truncate rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {p.name}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </nav>

      <div className="border-t border-border p-2">
        <AccountMenu user={user} />
      </div>
    </div>
  );
}

function NavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = item.exact ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;
  return (
    <li>
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        className={cn(
          "relative flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
          active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
        )}
      >
        {active ? <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent" aria-hidden /> : null}
        <Icon className={cn("size-4", active ? "text-foreground" : "text-muted-foreground")} />
        {item.label}
      </Link>
    </li>
  );
}

function ProjectSwitcher({ projects, current }: { projects: Props["projects"]; current?: { id: string; name: string } }) {
  const router = useRouter();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted">
        <span className="min-w-0">
          <span className="block text-[11px] text-muted-foreground">Project</span>
          <span className="block truncate text-sm font-medium">{current?.name ?? "Unknown project"}</span>
        </span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuLabel>Projects</DropdownMenuLabel>
        {projects.map((p) => (
          <DropdownMenuItem key={p.id} onSelect={() => router.push(`/p/${p.id}`)}>
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
            {p.id === current?.id ? <Check className="!text-accent" /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/projects")}>
          <FolderKanban /> All projects
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function OrgSwitcher({ organizations, activeOrg, role }: { organizations: Props["organizations"]; activeOrg: Props["activeOrg"]; role: string }) {
  const router = useRouter();
  const [creating, setCreating] = React.useState(false);

  async function switchTo(id: string) {
    if (id === activeOrg.id) return;
    const { error } = await authClient.organization.setActive({ organizationId: id });
    if (error) {
      toast.error(error.message ?? "Could not switch organization");
      return;
    }
    router.push("/projects");
    router.refresh();
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex w-full items-center gap-2.5 rounded-md border border-border bg-surface-2/50 px-2 py-1.5 text-left hover:border-border-strong"
          data-testid="org-switcher"
        >
          <span className="grid size-6 shrink-0 place-items-center rounded-sm bg-muted text-[11px] font-semibold uppercase">
            {activeOrg.name.slice(0, 1)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{activeOrg.name}</span>
            <span className="block text-[11px] capitalize text-muted-foreground">{role}</span>
          </span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-60">
          <DropdownMenuLabel>Organizations</DropdownMenuLabel>
          {organizations.map((o) => (
            <DropdownMenuItem key={o.id} onSelect={() => switchTo(o.id)}>
              <Building2 />
              <span className="min-w-0 flex-1 truncate">{o.name}</span>
              {o.id === activeOrg.id ? <Check className="!text-accent" /> : null}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setCreating(true)}>
            <Plus /> New organization
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent title="New organization" description="You will be the owner. You can invite members afterwards.">
          <CreateOrgForm
            onDone={() => {
              setCreating(false);
              router.push("/projects");
              router.refresh();
            }}
          />
        </DialogContent>
      </Dialog>
    </>
  );
}

function CreateOrgForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  return (
    <form
      className="grid gap-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setPending(true);
        setError(null);
        const slug = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "org"}-${Math.random().toString(36).slice(2, 6)}`;
        const { data, error } = await authClient.organization.create({ name: name.trim(), slug });
        if (error || !data) {
          setError(error?.message ?? "Could not create the organization");
          setPending(false);
          return;
        }
        await authClient.organization.setActive({ organizationId: data.id });
        setPending(false);
        onDone();
      }}
    >
      <Field label="Name" htmlFor="new-org-name">
        <Input id="new-org-name" required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={pending} disabled={!name.trim()}>
          Create organization
        </Button>
      </div>
    </form>
  );
}

function AccountMenu({ user }: { user: Props["user"] }) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme !== "light";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-muted" data-testid="account-menu">
        <span className="grid size-6 shrink-0 place-items-center overflow-hidden rounded-full bg-muted text-[11px] font-medium uppercase">
          {user.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={user.image} alt="" className="size-full object-cover" referrerPolicy="no-referrer" />
          ) : (
            (user.name || user.email).slice(0, 1)
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">{user.name || user.email}</span>
          <span className="block truncate text-[11px] text-muted-foreground">{user.email}</span>
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" className="w-56">
        <DropdownMenuItem onSelect={() => router.push("/settings/account")}>
          <UserRound /> Account
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => setTheme(isDark ? "light" : "dark")}>
          {isDark ? <Sun /> : <Moon />} {isDark ? "Light theme" : "Dark theme"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            await authClient.signOut();
            router.push("/sign-in");
            router.refresh();
          }}
        >
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
