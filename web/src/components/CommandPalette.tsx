import { useQuery } from "@tanstack/react-query";
import { Activity, Boxes, LayoutDashboard, ListTree, MessagesSquare, Settings } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { api } from "@/lib/api";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/instances", label: "Instances", icon: Boxes },
  { to: "/jobs", label: "Jobs", icon: Activity },
  { to: "/sessions", label: "Sessions", icon: MessagesSquare },
  { to: "/usage", label: "Usage & Audit", icon: ListTree },
  { to: "/config", label: "Config", icon: Settings },
];

/** ⌘K palette: jump to a page, instance, or recent job. Opens on ⌘/Ctrl-K or a
 *  window "agenthook:command" event (dispatched by the sidebar search). */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const nav = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onEvent = () => setOpen(true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("agenthook:command", onEvent);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("agenthook:command", onEvent);
    };
  }, []);

  const instances = useQuery({ queryKey: ["instances"], queryFn: api.listInstances, enabled: open });
  const jobs = useQuery({ queryKey: ["jobs", {}], queryFn: () => api.listJobs({ limit: 20 }), enabled: open });

  const go = (to: string) => {
    setOpen(false);
    nav(to);
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Jump to a page, instance, or job…" />
      <CommandList>
        <CommandEmpty>No matches.</CommandEmpty>
        <CommandGroup heading="Go to">
          {NAV.map(({ to, label, icon: Icon }) => (
            <CommandItem key={to} value={`go ${label}`} onSelect={() => go(to)}>
              <Icon className="h-4 w-4 text-muted-foreground" />
              {label}
            </CommandItem>
          ))}
        </CommandGroup>
        {instances.data && instances.data.length > 0 && (
          <CommandGroup heading="Instances">
            {instances.data.map((i) => (
              <CommandItem key={i.name} value={`instance ${i.name}`} onSelect={() => go(`/instances/${i.name}`)}>
                <Boxes className="h-4 w-4 text-muted-foreground" />
                {i.name}
                <span className="ml-auto text-xs text-muted-foreground">{i.engine}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
        {jobs.data && jobs.data.length > 0 && (
          <CommandGroup heading="Recent jobs">
            {jobs.data.slice(0, 8).map((j) => (
              <CommandItem key={j.id} value={`job ${j.id} ${j.instance}`} onSelect={() => go(`/jobs/${j.id}`)}>
                <span className="font-mono text-xs text-muted-foreground">{j.id}</span>
                <span className="ml-auto">
                  <StatusBadge status={j.status} />
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
