import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "@/components/ui/sonner";
import { api, ApiError } from "@/lib/api";

// Editable global config fields (secrets like admin_token come back masked and
// are read-only here).
const NUMERIC = ["port", "workers", "default_concurrency", "truncate_chars", "approval_ttl_s", "callback_max_attempts"];

export function Config() {
  const qc = useQueryClient();
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => api.getConfig() });
  const [draft, setDraft] = useState<Record<string, unknown>>({});

  const value = (k: string) => (k in draft ? draft[k] : cfg.data?.[k]);
  const set = (k: string, v: unknown) => setDraft((d) => ({ ...d, [k]: v }));

  const save = useMutation({
    mutationFn: () => api.patchConfig(draft),
    onSuccess: () => { toast.success("Config saved"); setDraft({}); qc.invalidateQueries({ queryKey: ["config"] }); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed"),
  });

  if (cfg.isLoading) return <p className="text-muted-foreground">Loading…</p>;

  const text = (k: string, label: string) => (
    <div className="grid grid-cols-[200px_1fr] items-center gap-3">
      <Label>{label}</Label>
      <Input
        value={String(value(k) ?? "")}
        type={NUMERIC.includes(k) ? "number" : "text"}
        onChange={(e) => set(k, NUMERIC.includes(k) ? Number(e.target.value) : e.target.value)}
      />
    </div>
  );

  return (
    <div className="space-y-6">
      <PageHeader title="Global config" subtitle="Server, approval, and retention settings. Secrets stay masked." />
      <Card>
        <CardHeader><CardTitle>Server</CardTitle></CardHeader>
        <CardContent className="grid max-w-2xl gap-4">
          {text("host", "Host")}
          {text("port", "Port")}
          {text("default_concurrency", "Default concurrency")}
          {text("docker_image", "Docker image")}
          <div className="grid grid-cols-[200px_1fr] items-center gap-3">
            <Label>Use Docker</Label>
            <Switch checked={Boolean(value("use_docker"))} onCheckedChange={(v) => set("use_docker", v)} />
          </div>
          <div className="grid grid-cols-[200px_1fr] items-center gap-3">
            <Label>Admin remote</Label>
            <div className="flex items-center gap-3">
              <Switch checked={Boolean(value("admin_remote"))} onCheckedChange={(v) => set("admin_remote", v)} />
              <span className="text-xs text-muted-foreground">allow /admin from non-loopback clients</span>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Approval & retention</CardTitle></CardHeader>
        <CardContent className="grid max-w-2xl gap-4">
          {text("public_base_url", "Public base URL")}
          {text("approval_ttl_s", "Approval TTL (s)")}
          {text("truncate_chars", "Truncate chars")}
          <div className="grid grid-cols-[200px_1fr] items-center gap-3">
            <Label>Admin token</Label>
            <Input value={String(cfg.data?.admin_token ?? "")} disabled />
          </div>
        </CardContent>
      </Card>

      <Button onClick={() => save.mutate()} disabled={save.isPending || Object.keys(draft).length === 0}>
        Save changes
      </Button>
    </div>
  );
}
