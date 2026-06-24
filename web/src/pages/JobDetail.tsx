import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { openJobStream } from "@/lib/sse";
import { fmtCost, fmtTime } from "@/lib/utils";

const TERMINAL = ["success", "error", "timeout", "interrupted", "rejected", "expired", "blocked", "failed-checks"];

export function JobDetail() {
  const { id = "" } = useParams();
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api.getJob(id) });

  const [log, setLog] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    setLog([]);
    setText("");
    setDone(null);
    const close = openJobStream(id, {
      onLog: (line) => setLog((l) => [...l, line]),
      onText: (d) => setText((t) => t + d),
      onDone: (status) => setDone(status),
    });
    return close;
  }, [id]);

  useEffect(() => {
    logEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [log, text]);

  const j = job.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="font-mono text-xl font-bold">{id}</h1>
        {(done || j?.status) && <StatusBadge status={done ?? j!.status} />}
      </div>

      {j && (
        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm md:grid-cols-3">
            <Meta label="Instance" value={j.instance} />
            <Meta label="Deliverable" value={j.deliverable} />
            <Meta label="Mode" value={j.mode} />
            <Meta label="Thread" value={j.thread_key ?? "—"} />
            <Meta label="Cost" value={fmtCost((j.usage?.cost_usd as number) ?? null)} />
            <Meta label="Created" value={fmtTime(j.created_at)} />
            {j.error_message && <Meta label="Error" value={j.error_message} />}
            {j.pr_url && <Meta label="PR" value={j.pr_url} />}
          </CardContent>
        </Card>
      )}

      {text && (
        <Card>
          <CardHeader><CardTitle>Engine output</CardTitle></CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-sm text-brand-bone">{text}</pre>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Live log
            {!done && !TERMINAL.includes(j?.status ?? "") && <span className="text-xs text-brand-amber">▸ streaming</span>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-[420px] overflow-auto rounded-md border border-border bg-background p-3 font-mono text-xs text-muted-foreground">
            {log.length === 0 && <span className="text-muted-foreground">Waiting for output…</span>}
            {log.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
            <div ref={logEnd} />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="break-all">{value}</div>
    </div>
  );
}
