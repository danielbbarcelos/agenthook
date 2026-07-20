import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  Boxes,
  LayoutDashboard,
  ListTree,
  LogOut,
  type LucideIcon,
  Menu,
  MessagesSquare,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  Sun,
  X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Brand, type ServerStatus } from "@/components/Brand";
import { CommandPalette } from "@/components/CommandPalette";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheck,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { type Theme, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}
const GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Operação",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/jobs", label: "Jobs", icon: Activity },
      { to: "/sessions", label: "Sessions", icon: MessagesSquare },
    ],
  },
  {
    label: "Gestão",
    items: [
      { to: "/instances", label: "Instances", icon: Boxes },
      { to: "/usage", label: "Usage & Audit", icon: ListTree },
    ],
  },
  { label: "Sistema", items: [{ to: "/config", label: "Config", icon: Settings }] },
];

function useServerStatus(): { status: ServerStatus; host: string; running: number } {
  const health = useQuery({ queryKey: ["healthz"], queryFn: api.health, refetchInterval: 5000, retry: false });
  const jobs = useQuery({ queryKey: ["jobs", {}], queryFn: () => api.listJobs({ limit: 100 }), refetchInterval: 5000 });
  const config = useQuery({ queryKey: ["config"], queryFn: api.getConfig });
  const running = jobs.data?.filter((j) => j.status === "running").length ?? 0;
  const status: ServerStatus = health.isError
    ? "down"
    : health.isLoading
      ? "unknown"
      : running > 0
        ? "up-running"
        : "up";
  const host = config.data ? `${config.data.host}:${config.data.port}` : "—";
  return { status, host, running };
}

function NavRow({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const link = (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-md py-2 text-sm transition-colors",
          collapsed ? "justify-center px-2" : "px-3",
          isActive
            ? "text-primary before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-full before:bg-primary"
            : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )
      }
    >
      <item.icon className="h-[18px] w-[18px] shrink-0" />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  );
  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{item.label}</TooltipContent>
    </Tooltip>
  );
}

function ServerChip({ status, host, collapsed }: { status: ServerStatus; host: string; collapsed: boolean }) {
  const up = status === "up" || status === "up-running";
  if (collapsed) return null;
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-background/40 px-2.5 py-1.5 text-xs">
      <span className={cn("text-[10px]", up ? "text-brand-sage" : "text-muted-foreground")}>●</span>
      <span className="text-muted-foreground">{up ? "connected" : "offline"}</span>
      <span className="ml-auto font-mono text-muted-foreground">{host}</span>
    </div>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const opts: { value: Theme; label: string; icon: LucideIcon }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];
  const Active = (opts.find((o) => o.value === theme) ?? opts[2]).icon;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change theme">
          <Active className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {opts.map(({ value, label, icon: Icon }) => (
          <DropdownMenuItem key={value} onSelect={() => setTheme(value)}>
            <Icon className="h-4 w-4 text-muted-foreground" />
            {label}
            <DropdownMenuCheck active={theme === value} />
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SidebarBody({
  collapsed,
  status,
  host,
  onNavigate,
}: {
  collapsed: boolean;
  status: ServerStatus;
  host: string;
  onNavigate?: () => void;
}) {
  return (
    <div className="flex h-full flex-col gap-4">
      <div className={cn("pt-5", collapsed ? "px-3" : "px-5")}>
        <Brand status={status} collapsed={collapsed} />
      </div>

      <div className={cn("space-y-2", collapsed ? "px-2" : "px-4")}>
        {!collapsed && <ServerChip status={status} host={host} collapsed={collapsed} />}
        <button
          onClick={() => window.dispatchEvent(new Event("agenthook:command"))}
          className={cn(
            "flex w-full items-center gap-2 rounded-md border border-border bg-background/40 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground",
            collapsed ? "justify-center px-2" : "px-2.5",
          )}
        >
          <Search className="h-4 w-4" />
          {!collapsed && (
            <>
              <span>Search</span>
              <kbd className="ml-auto rounded border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                ⌘K
              </kbd>
            </>
          )}
        </button>
      </div>

      <nav className={cn("flex-1 space-y-5 overflow-y-auto", collapsed ? "px-2" : "px-4")}>
        {GROUPS.map((g) => (
          <div key={g.label} className="space-y-1">
            {!collapsed && <div className="eyebrow px-3 pb-1">{g.label}</div>}
            {g.items.map((item) => (
              <NavRow key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </div>
        ))}
      </nav>

      <div className={cn("border-t border-border py-3", collapsed ? "px-2" : "px-4")}>
        {collapsed ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="w-full text-muted-foreground"
                onClick={() => {
                  void api.logout();
                  location.assign("/ui/#/login");
                }}
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="right">Sign out</TooltipContent>
          </Tooltip>
        ) : (
          <div className="flex items-center justify-between">
            <span className="truncate font-mono text-xs text-muted-foreground">admin</span>
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => {
                void api.logout();
                location.assign("/ui/#/login");
              }}
            >
              <LogOut className="h-4 w-4" /> Sign out
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Breadcrumb() {
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  return (
    <div className="flex items-center gap-2 truncate text-sm">
      <span className="text-primary">agenthook</span>
      {parts.length === 0 && <span className="text-muted-foreground"><span aria-hidden>▸</span> dashboard</span>}
      {parts.map((p, i) => (
        <span key={i} className="flex items-center gap-2 truncate">
          <span aria-hidden className="text-muted-foreground">▸</span>
          <span className={i === parts.length - 1 ? "truncate text-foreground" : "text-muted-foreground"}>{p}</span>
        </span>
      ))}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("agenthook.rail") === "1");
  const [drawer, setDrawer] = useState(false);
  const { status, host, running } = useServerStatus();

  const toggleCollapse = () => {
    setCollapsed((c) => {
      localStorage.setItem("agenthook.rail", c ? "0" : "1");
      return !c;
    });
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex min-h-screen bg-background">
        {/* Desktop sidebar */}
        <aside
          className={cn(
            "hidden shrink-0 border-r border-border bg-surface lg:sticky lg:top-0 lg:block lg:h-screen",
            collapsed ? "lg:w-[72px]" : "lg:w-64",
          )}
        >
          <SidebarBody collapsed={collapsed} status={status} host={host} />
        </aside>

        {/* Mobile drawer */}
        <DialogPrimitive.Root open={drawer} onOpenChange={setDrawer}>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 lg:hidden" />
            <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 w-72 border-r border-border bg-surface focus:outline-none lg:hidden">
              <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
              <DialogPrimitive.Close className="absolute right-3 top-4 text-muted-foreground hover:text-foreground">
                <X className="h-5 w-5" />
              </DialogPrimitive.Close>
              <SidebarBody collapsed={false} status={status} host={host} onNavigate={() => setDrawer(false)} />
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-border bg-surface/80 px-4 backdrop-blur sm:px-6">
            <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu">
              <Menu className="h-5 w-5" />
            </Button>
            <Button variant="ghost" size="icon" className="hidden lg:inline-flex" onClick={toggleCollapse} aria-label="Toggle sidebar">
              {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
            </Button>
            <Breadcrumb />
            <div className="ml-auto flex items-center gap-2">
              {running > 0 && (
                <span className="hidden items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-primary sm:inline-flex">
                  <span aria-hidden>▸</span>
                  {running} running
                </span>
              )}
              <ThemeToggle />
            </div>
          </header>
          <main className="flex-1 overflow-auto p-4 sm:p-6 lg:p-8">{children}</main>
        </div>
      </div>
      <CommandPalette />
    </TooltipProvider>
  );
}
