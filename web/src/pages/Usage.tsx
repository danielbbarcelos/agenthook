import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { fmtCost, fmtTime } from "@/lib/utils";

export function Usage() {
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => api.usage() });
  const audit = useQuery({ queryKey: ["audit"], queryFn: () => api.audit({ limit: 200 }) });

  return (
    <div>
      <PageHeader title="Usage & Audit" subtitle="What ran, who asked, and what it cost." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="eyebrow">Total jobs</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-bold text-foreground">{usage.data?.jobs ?? "—"}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="eyebrow">Total cost</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-bold text-primary">{fmtCost(usage.data?.cost_usd)}</div></CardContent>
        </Card>
      </div>
      <Card className="mt-6">
        <CardHeader><CardTitle>Audit log</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Status</TableHead>
                <TableHead>Job</TableHead>
                <TableHead>Instance</TableHead>
                <TableHead>Requester</TableHead>
                <TableHead>Cost</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {audit.data?.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>{r.status ? <StatusBadge status={r.status} /> : "—"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{r.job_id}</TableCell>
                  <TableCell className="text-muted-foreground">{r.instance}</TableCell>
                  <TableCell>{r.requester ?? "—"}</TableCell>
                  <TableCell>{fmtCost(r.cost_usd)}</TableCell>
                  <TableCell className="text-muted-foreground">{fmtTime(r.created_at)}</TableCell>
                </TableRow>
              ))}
              {audit.data?.length === 0 && <TableRow><TableCell colSpan={6} className="py-10 text-center text-muted-foreground">Nothing recorded yet. Runs show up here as they finish.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
