import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { InstanceState } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/sonner";
import { api, ApiError } from "@/lib/api";
import type { CreateInstanceResult } from "@/lib/types";

const DELIVERABLES = ["analysis", "action", "patch", "commit", "pr"];

export function Instances() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["instances"], queryFn: api.listInstances });
  const [open, setOpen] = useState(false);
  const [keyResult, setKeyResult] = useState<CreateInstanceResult | null>(null);

  const [name, setName] = useState("");
  const [repo, setRepo] = useState("");
  const [deliverable, setDeliverable] = useState("analysis");

  const create = useMutation({
    mutationFn: () =>
      api.createInstance({
        name,
        deliverable,
        repos: repo ? [{ url: repo }] : [],
      }),
    onSuccess: (res) => {
      setOpen(false);
      setName("");
      setRepo("");
      setKeyResult(res);
      qc.invalidateQueries({ queryKey: ["instances"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to create instance"),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Instances</h1>
        <Button onClick={() => setOpen(true)}>
          <Plus className="h-4 w-4" /> New instance
        </Button>
      </div>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Engine</TableHead>
              <TableHead>Deliverable</TableHead>
              <TableHead>Repos</TableHead>
              <TableHead>State</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            )}
            {data?.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  No instances yet — create one to get started.
                </TableCell>
              </TableRow>
            )}
            {data?.map((i) => (
              <TableRow key={i.name}>
                <TableCell>
                  <Link to={`/instances/${i.name}`} className="font-medium text-brand-amber hover:underline">
                    {i.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground">{i.engine}</TableCell>
                <TableCell>{i.deliverable}</TableCell>
                <TableCell className="text-muted-foreground">{i.repos.join(", ") || "—"}</TableCell>
                <TableCell>
                  <InstanceState paused={i.paused} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {/* Create dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New instance</DialogTitle>
            <DialogDescription>An immutable encryption key is generated and shown once.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="bugbot" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="repo">Repo URL (optional)</Label>
              <Input id="repo" value={repo} onChange={(e) => setRepo(e.target.value)} placeholder="git@github.com:me/app.git" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="deliverable">Deliverable</Label>
              <select
                id="deliverable"
                value={deliverable}
                onChange={(e) => setDeliverable(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              >
                {DELIVERABLES.map((d) => (
                  <option key={d} value={d} className="bg-card">
                    {d}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* One-time encryption key — must be acknowledged */}
      <Dialog open={!!keyResult} onOpenChange={(v) => !v && setKeyResult(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="text-brand-amber">🔐 Encryption key — shown once</DialogTitle>
            <DialogDescription>
              Store this key now. It is the only copy and cannot be recovered; it is immutable for the life of the
              instance.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <code className="block break-all rounded-md border border-border bg-background p-3 text-sm text-brand-amber">
              {keyResult?.encryption_key}
            </code>
            <p className="text-xs text-muted-foreground">fingerprint: {keyResult?.fingerprint}</p>
          </div>
          <DialogFooter>
            <Button
              onClick={() => {
                navigator.clipboard?.writeText(keyResult?.encryption_key ?? "");
                toast.success("Key copied");
              }}
              variant="outline"
            >
              Copy
            </Button>
            <Button onClick={() => setKeyResult(null)}>I stored it</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
