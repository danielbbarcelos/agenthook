import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fmtCost } from "@/lib/utils";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold text-brand-amber">{value}</div>
      </CardContent>
    </Card>
  );
}

export function Dashboard() {
  const instances = useQuery({ queryKey: ["instances"], queryFn: api.listInstances });
  const jobs = useQuery({ queryKey: ["jobs", {}], queryFn: () => api.listJobs({ limit: 100 }), refetchInterval: 4000 });
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => api.usage() });

  const running = jobs.data?.filter((j) => j.status === "running").length ?? 0;
  const queued = jobs.data?.filter((j) => j.status === "queued").length ?? 0;
  const recent = jobs.data?.slice(0, 8) ?? [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Instances" value={instances.data?.length ?? "—"} />
        <Stat label="Running" value={running} />
        <Stat label="Queued" value={queued} />
        <Stat label="Total cost" value={fmtCost(usage.data?.cost_usd)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent jobs</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {recent.length === 0 && <p className="text-sm text-muted-foreground">No jobs yet.</p>}
          {recent.map((j) => (
            <Link
              key={j.id}
              to={`/jobs/${j.id}`}
              className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-accent"
            >
              <div className="flex items-center gap-3">
                <StatusBadge status={j.status} />
                <span className="text-sm text-muted-foreground">{j.instance}</span>
              </div>
              <span className="font-mono text-xs text-muted-foreground">{j.id}</span>
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
