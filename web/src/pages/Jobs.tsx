import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { fmtCost, fmtTime } from "@/lib/utils";

const STATUSES = ["", "queued", "running", "awaiting_approval", "success", "failed-checks", "blocked", "error", "timeout"];

export function Jobs() {
  const [instance, setInstance] = useState("");
  const [status, setStatus] = useState("");
  const jobs = useQuery({
    queryKey: ["jobs", { instance, status }],
    queryFn: () => api.listJobs({ instance: instance || undefined, status: status || undefined, limit: 200 }),
    refetchInterval: 4000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Jobs</h1>
      <div className="flex gap-2">
        <Input className="w-56" placeholder="filter by instance" value={instance} onChange={(e) => setInstance(e.target.value)} />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s} className="bg-card">{s || "all statuses"}</option>
          ))}
        </select>
      </div>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Job</TableHead>
              <TableHead>Instance</TableHead>
              <TableHead>Deliverable</TableHead>
              <TableHead>Cost</TableHead>
              <TableHead>Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.data?.map((j) => (
              <TableRow key={j.id}>
                <TableCell><StatusBadge status={j.status} /></TableCell>
                <TableCell>
                  <Link to={`/jobs/${j.id}`} className="font-mono text-xs text-brand-amber hover:underline">{j.id}</Link>
                </TableCell>
                <TableCell className="text-muted-foreground">{j.instance}</TableCell>
                <TableCell>{j.deliverable}</TableCell>
                <TableCell>{fmtCost((j.usage?.cost_usd as number) ?? null)}</TableCell>
                <TableCell className="text-muted-foreground">{fmtTime(j.created_at)}</TableCell>
              </TableRow>
            ))}
            {jobs.data?.length === 0 && <TableRow><TableCell colSpan={6} className="text-muted-foreground">No jobs.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
