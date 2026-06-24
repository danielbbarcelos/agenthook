import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/utils";

export function Sessions() {
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.listSessions() });
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Sessions</h1>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Thread key</TableHead>
              <TableHead>Instance</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Jobs</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.data?.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium">{s.thread_key}</TableCell>
                <TableCell className="text-muted-foreground">{s.instance}</TableCell>
                <TableCell>{s.status}</TableCell>
                <TableCell>{s.job_count}</TableCell>
                <TableCell className="text-muted-foreground">{fmtTime(s.updated_at)}</TableCell>
              </TableRow>
            ))}
            {sessions.data?.length === 0 && <TableRow><TableCell colSpan={5} className="text-muted-foreground">No sessions.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
