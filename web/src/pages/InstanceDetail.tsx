import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Pause, Play, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CodeEditor } from "@/components/CodeEditor";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { InstanceState } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "@/components/ui/sonner";
import { api, ApiError } from "@/lib/api";
import type { Instance } from "@/lib/types";

function err(e: unknown) {
  toast.error(e instanceof ApiError ? e.message : "Request failed");
}

export function InstanceDetail() {
  const { name = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [confirmDel, setConfirmDel] = useState(false);

  const inst = useQuery({ queryKey: ["instance", name], queryFn: () => api.getInstance(name) });

  const pause = useMutation({
    mutationFn: (paused: boolean) => (paused ? api.pauseInstance(name) : api.resumeInstance(name)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instance", name] }),
    onError: err,
  });
  const del = useMutation({
    mutationFn: () => api.deleteInstance(name),
    onSuccess: () => {
      toast.success(`Deleted ${name}`);
      qc.invalidateQueries({ queryKey: ["instances"] });
      nav("/instances");
    },
    onError: err,
  });

  if (inst.isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (inst.isError || !inst.data) return <p className="text-destructive">Instance not found.</p>;
  const i = inst.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">{i.name}</h1>
          <InstanceState paused={i.paused} />
        </div>
        <div className="flex gap-2">
          {i.paused ? (
            <Button variant="outline" size="sm" onClick={() => pause.mutate(false)}>
              <Play className="h-4 w-4" /> Resume
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={() => pause.mutate(true)}>
              <Pause className="h-4 w-4" /> Pause
            </Button>
          )}
          <Button variant="destructive" size="sm" onClick={() => setConfirmDel(true)}>
            <Trash2 className="h-4 w-4" /> Delete
          </Button>
        </div>
      </div>

      <Tabs defaultValue="config">
        <TabsList>
          <TabsTrigger value="config">Config</TabsTrigger>
          <TabsTrigger value="repos">Repos</TabsTrigger>
          <TabsTrigger value="env">Env</TabsTrigger>
          <TabsTrigger value="engine-auth">Engine auth</TabsTrigger>
          <TabsTrigger value="auth">Webhook auth</TabsTrigger>
          <TabsTrigger value="verify">Verify</TabsTrigger>
          <TabsTrigger value="mcp">MCP</TabsTrigger>
          <TabsTrigger value="context">CLAUDE.md</TabsTrigger>
          <TabsTrigger value="guardrails">Guardrails</TabsTrigger>
          <TabsTrigger value="skills">Skills</TabsTrigger>
        </TabsList>

        <TabsContent value="config"><ConfigPanel inst={i} /></TabsContent>
        <TabsContent value="repos"><ReposPanel name={name} /></TabsContent>
        <TabsContent value="env"><EnvPanel name={name} /></TabsContent>
        <TabsContent value="engine-auth"><EngineAuthPanel inst={i} /></TabsContent>
        <TabsContent value="auth"><JsonPanel title="Webhook auth" value={i.webhook_auth} save={(v) => api.setAuth(name, v)} /></TabsContent>
        <TabsContent value="verify"><JsonPanel title="Verify (self-heal)" value={i.verify} save={(v) => api.setVerify(name, v)} /></TabsContent>
        <TabsContent value="mcp"><JsonPanel title="MCP servers" value={i.mcp} save={(v) => api.setMcp(name, v)} /></TabsContent>
        <TabsContent value="context"><ContextPanel name={name} /></TabsContent>
        <TabsContent value="guardrails"><GuardrailsPanel name={name} /></TabsContent>
        <TabsContent value="skills"><SkillsPanel name={name} /></TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirmDel}
        onOpenChange={setConfirmDel}
        title={`Delete ${name}?`}
        description="Removes the instance and all its state (key, env, repos, logs). This cannot be undone."
        confirmLabel="Delete"
        destructive
        onConfirm={() => del.mutate()}
      />
    </div>
  );
}

// --- Config -----------------------------------------------------------------

function ConfigPanel({ inst }: { inst: Instance }) {
  const qc = useQueryClient();
  const [engine, setEngine] = useState(inst.engine);
  const [model, setModel] = useState(inst.model ?? "");
  const [deliverable, setDeliverable] = useState(inst.deliverable);
  const [branch, setBranch] = useState(inst.branch_base);
  const [prompt, setPrompt] = useState(inst.default_prompt ?? "");

  const engines = useQuery({ queryKey: ["engines"], queryFn: () => api.listEngines() });

  const save = useMutation({
    mutationFn: () =>
      api.patchInstance(inst.name, {
        engine,
        model: model || null,
        deliverable,
        branch_base: branch,
        default_prompt: prompt || null,
      }),
    onSuccess: () => {
      toast.success("Saved");
      qc.invalidateQueries({ queryKey: ["instance", inst.name] });
    },
    onError: err,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Configuration</CardTitle>
      </CardHeader>
      <CardContent className="grid max-w-xl gap-4">
        <Field label="Engine">
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
          >
            {(engines.data ?? [{ name: inst.engine }]).map((e) => (
              <option key={e.name} value={e.name} className="bg-card">{e.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Model"><Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="(engine default)" /></Field>
        <Field label="Default deliverable">
          <select
            value={deliverable}
            onChange={(e) => setDeliverable(e.target.value)}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
          >
            {["analysis", "action", "patch", "commit", "pr"].map((d) => (
              <option key={d} value={d} className="bg-card">{d}</option>
            ))}
          </select>
        </Field>
        <Field label="Base branch"><Input value={branch} onChange={(e) => setBranch(e.target.value)} /></Field>
        <Field label="Default prompt"><Input value={prompt} onChange={(e) => setPrompt(e.target.value)} /></Field>
        <div>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>Save</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[160px_1fr] items-center gap-3">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

// --- Repos ------------------------------------------------------------------

function ReposPanel({ name }: { name: string }) {
  const qc = useQueryClient();
  const repos = useQuery({ queryKey: ["repos", name], queryFn: () => api.listRepos(name) });
  const [url, setUrl] = useState("");
  const add = useMutation({
    mutationFn: () => api.addRepo(name, { url }),
    onSuccess: () => { setUrl(""); qc.invalidateQueries({ queryKey: ["repos", name] }); },
    onError: err,
  });
  const remove = useMutation({
    mutationFn: (repo: string) => api.removeRepo(name, repo),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["repos", name] }),
    onError: err,
  });
  return (
    <Card>
      <CardHeader><CardTitle>Repository pool</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="git@github.com:me/app.git" />
          <Button onClick={() => add.mutate()} disabled={!url.trim()}>Add</Button>
        </div>
        <Table>
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>URL</TableHead><TableHead>Branch</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {repos.data?.map((r) => (
              <TableRow key={r.name}>
                <TableCell>{r.name}</TableCell>
                <TableCell className="text-muted-foreground">{r.url}</TableCell>
                <TableCell>{r.branch_base}</TableCell>
                <TableCell className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => remove.mutate(r.name)}><Trash2 className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
            {repos.data?.length === 0 && <TableRow><TableCell colSpan={4} className="text-muted-foreground">No repos.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// --- Env --------------------------------------------------------------------

function EnvPanel({ name }: { name: string }) {
  const qc = useQueryClient();
  const env = useQuery({ queryKey: ["env", name], queryFn: () => api.listEnv(name) });
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [secret, setSecret] = useState(true);

  const set = useMutation({
    mutationFn: () => api.setEnv(name, key, { value, secret }),
    onSuccess: () => { setKey(""); setValue(""); qc.invalidateQueries({ queryKey: ["env", name] }); },
    onError: err,
  });
  const remove = useMutation({
    mutationFn: (k: string) => api.deleteEnv(name, k),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["env", name] }),
    onError: err,
  });

  return (
    <Card>
      <CardHeader><CardTitle>Environment variables</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Input className="w-48" value={key} onChange={(e) => setKey(e.target.value)} placeholder="KEY" />
          <Input className="flex-1" value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" />
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <Switch checked={secret} onCheckedChange={setSecret} /> secret
          </label>
          <Button onClick={() => set.mutate()} disabled={!key.trim()}>Set</Button>
        </div>
        <p className="text-xs text-muted-foreground">Secret values are stored encrypted and shown masked — they never come back in cleartext.</p>
        <Table>
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Value</TableHead><TableHead>Secret</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            {env.data?.map((e) => (
              <TableRow key={e.name}>
                <TableCell className="font-medium">{e.name}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{e.value}</TableCell>
                <TableCell>{e.secret ? "yes" : "no"}</TableCell>
                <TableCell className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => remove.mutate(e.name)}><Trash2 className="h-4 w-4" /></Button>
                </TableCell>
              </TableRow>
            ))}
            {env.data?.length === 0 && <TableRow><TableCell colSpan={4} className="text-muted-foreground">No env vars.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// --- Engine auth (the coding engine's own login) ----------------------------

function EngineAuthPanel({ inst }: { inst: Instance }) {
  const qc = useQueryClient();
  const name = inst.name;
  const [copied, setCopied] = useState(false);
  const [login, setLogin] = useState<{ session: string; url: string } | null>(null);
  const [code, setCode] = useState("");
  const [urlCopied, setUrlCopied] = useState(false);

  const status = useQuery({
    queryKey: ["engine-auth", name],
    queryFn: () => api.getEngineAuth(name),
    refetchInterval: 3000, // live status while the operator logs in elsewhere
  });

  const setMode = useMutation({
    mutationFn: (mode: string) => api.patchInstance(name, { engine_auth: mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["instance", name] });
      qc.invalidateQueries({ queryKey: ["engine-auth", name] });
    },
    onError: err,
  });
  const logout = useMutation({
    mutationFn: () => api.logoutEngineAuth(name),
    onSuccess: () => {
      toast.success("Subscription disconnected");
      qc.invalidateQueries({ queryKey: ["engine-auth", name] });
    },
    onError: err,
  });
  const startLogin = useMutation({
    mutationFn: () => api.startEngineLogin(name),
    onSuccess: (r) => { setLogin(r); setCode(""); },
    onError: err,
  });
  const submitCode = useMutation({
    mutationFn: () => api.submitEngineLoginCode(name, { session: login!.session, code }),
    onSuccess: () => {
      toast.success("Subscription connected");
      setLogin(null);
      setCode("");
      qc.invalidateQueries({ queryKey: ["engine-auth", name] });
    },
    onError: err,
  });

  const s = status.data;
  const mode = inst.engine_auth;
  const supportsSub = s?.supports_subscription ?? false;
  const supportsTokenLogin = s?.supports_token_login ?? false;
  const connected = s?.authenticated === true;
  const cmd = s?.login_command ?? `agenthook login ${name}`;

  const copy = () => {
    navigator.clipboard?.writeText(cmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const copyUrl = () => {
    navigator.clipboard?.writeText(login?.url ?? "");
    setUrlCopied(true);
    setTimeout(() => setUrlCopied(false), 1500);
  };

  return (
    <Card>
      <CardHeader><CardTitle>Engine auth</CardTitle></CardHeader>
      <CardContent className="max-w-xl space-y-5">
        <p className="text-sm text-muted-foreground">
          How <span className="text-foreground">{inst.engine}</span> authenticates when running jobs. This is the
          coding engine's own login — separate from the webhook auth that guards inbound requests.
        </p>

        {/* mode selector */}
        <div className="space-y-2">
          <Label>Mode</Label>
          <div className="flex gap-2">
            {[
              { v: "subscription", label: "Subscription", disabled: !supportsSub },
              { v: "api-key", label: "API key", disabled: false },
            ].map((o) => (
              <button
                key={o.v}
                disabled={o.disabled || setMode.isPending}
                onClick={() => mode !== o.v && setMode.mutate(o.v)}
                className={`flex-1 rounded-md border px-3 py-2 text-sm transition-colors ${
                  mode === o.v
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:hover:text-muted-foreground"
                }`}
              >
                {o.label}
                {o.disabled && <span className="block text-[11px] opacity-70">not supported by {inst.engine}</span>}
              </button>
            ))}
          </div>
        </div>

        {mode === "subscription" ? (
          <div className="space-y-4 rounded-md border border-border bg-background/40 p-4">
            <div className="flex items-center gap-2 text-sm">
              <span className={connected ? "text-brand-sage" : "text-muted-foreground"}>●</span>
              <span className="text-foreground">{connected ? "Connected" : "Not connected"}</span>
              {status.isFetching && <span className="text-xs text-muted-foreground">⟳ checking…</span>}
            </div>

            {!connected && supportsTokenLogin && (
              <div className="space-y-3">
                {!login ? (
                  <>
                    <p className="text-sm text-muted-foreground">
                      Connect your Claude subscription without leaving the panel: we open the OAuth flow,
                      you authorize in your browser, and paste back the code Claude shows you.
                    </p>
                    <Button size="sm" onClick={() => startLogin.mutate()} disabled={startLogin.isPending}>
                      {startLogin.isPending ? "Starting…" : "Connect in browser"}
                    </Button>
                  </>
                ) : (
                  <>
                    <div className="space-y-1">
                      <p className="text-sm text-muted-foreground">
                        <span className="text-foreground">1.</span> Open this URL, sign in, and approve:
                      </p>
                      <div className="flex items-center gap-2">
                        <a
                          href={login.url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex flex-1 items-center gap-1.5 break-all rounded border border-border bg-background p-2 font-mono text-xs text-brand-cyan hover:underline"
                        >
                          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                          {login.url}
                        </a>
                        <Button size="sm" variant="outline" onClick={copyUrl}>
                          {urlCopied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm text-muted-foreground">
                        <span className="text-foreground">2.</span> Paste the code Claude gives you:
                      </p>
                      <div className="flex items-center gap-2">
                        <Input
                          value={code}
                          onChange={(e) => setCode(e.target.value)}
                          placeholder="paste code here"
                          onKeyDown={(e) => e.key === "Enter" && code.trim() && submitCode.mutate()}
                        />
                        <Button size="sm" onClick={() => submitCode.mutate()} disabled={!code.trim() || submitCode.isPending}>
                          {submitCode.isPending ? "Verifying…" : "Submit"}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => { setLogin(null); setCode(""); }}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {!connected && (
              <details className="text-sm text-muted-foreground">
                <summary className="cursor-pointer select-none hover:text-foreground">
                  Prefer the terminal?
                </summary>
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 break-all rounded border border-border bg-background p-2 font-mono text-sm text-foreground">
                    {cmd}
                  </code>
                  <Button size="sm" variant="outline" onClick={copy}>
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  </Button>
                </div>
              </details>
            )}

            {connected && (
              <Button size="sm" variant="outline" onClick={() => logout.mutate()} disabled={logout.isPending}>
                Disconnect
              </Button>
            )}
          </div>
        ) : (
          <div className="rounded-md border border-border bg-background/40 p-4 text-sm text-muted-foreground">
            API-key mode reads the engine's key from the instance's environment. Set{" "}
            <code className="text-brand-cyan">ANTHROPIC_API_KEY</code> (or your provider's key) as a secret in the{" "}
            <span className="text-foreground">Env</span> tab.
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --- JSON block (auth / verify / mcp) ---------------------------------------

function JsonPanel({
  title,
  value,
  save,
}: {
  title: string;
  value: Record<string, unknown>;
  save: (v: Record<string, unknown>) => Promise<unknown>;
}) {
  const [text, setText] = useState(JSON.stringify(value, null, 2));
  const mut = useMutation({
    mutationFn: async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(text || "{}");
      } catch {
        throw new ApiError(400, "Invalid JSON");
      }
      return save(parsed);
    },
    onSuccess: () => toast.success("Saved"),
    onError: err,
  });
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <CodeEditor value={text} onChange={setText} language="json" height="280px" />
        <Button onClick={() => mut.mutate()} disabled={mut.isPending}>Save</Button>
      </CardContent>
    </Card>
  );
}

// --- Context (CLAUDE.md) ----------------------------------------------------

function ContextPanel({ name }: { name: string }) {
  const ctx = useQuery({ queryKey: ["context", name], queryFn: () => api.getContext(name) });
  const [text, setText] = useState<string | null>(null);
  const body = text ?? ctx.data?.body ?? "";
  const mut = useMutation({
    mutationFn: () => api.setContext(name, body),
    onSuccess: () => toast.success("Saved"),
    onError: err,
  });
  return (
    <Card>
      <CardHeader><CardTitle>Context file (CLAUDE.md)</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {ctx.isLoading ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : (
          <CodeEditor value={body} onChange={setText} language="markdown" height="360px" />
        )}
        <Button onClick={() => mut.mutate()} disabled={mut.isPending}>Save</Button>
      </CardContent>
    </Card>
  );
}

// --- Guardrails (append-only) -----------------------------------------------

function GuardrailsPanel({ name }: { name: string }) {
  const qc = useQueryClient();
  const g = useQuery({ queryKey: ["guardrails", name], queryFn: () => api.getGuardrails(name) });
  const [extra, setExtra] = useState<string | null>(null);
  const [forceRo, setForceRo] = useState<boolean | null>(null);

  const extraVal = extra ?? g.data?.extra ?? "";
  const forceVal = forceRo ?? g.data?.force_read_only ?? false;

  const mut = useMutation({
    mutationFn: () => api.setGuardrails(name, { extra: extraVal || undefined, force_read_only: forceVal }),
    onSuccess: () => { toast.success("Guardrails saved"); qc.invalidateQueries({ queryKey: ["guardrails", name] }); },
    onError: err,
  });

  return (
    <Card>
      <CardHeader><CardTitle>Guardrails</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-md border border-brand-sage/30 bg-brand-sage/5 p-3 text-sm text-muted-foreground">
          <span className="text-brand-sage">● Baseline always on.</span> The global operator guardrail (confidentiality,
          anti-exfiltration, database safety, injection resistance) is an inviolable floor. This overlay is{" "}
          <span className="text-foreground">append-only</span>: you can add rules or harden, never disable a safety block.
        </div>
        <div className="space-y-2">
          <Label>Extra rules (appended to the baseline)</Label>
          <textarea
            className="flex min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm"
            value={extraVal}
            onChange={(e) => setExtra(e.target.value)}
            placeholder="Never write to the payments schema."
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={forceVal} onCheckedChange={(v) => setForceRo(v)} />
          Force read-only (harden: forbid edit/write tools)
        </label>
        <Button onClick={() => mut.mutate()} disabled={mut.isPending}>Save</Button>
      </CardContent>
    </Card>
  );
}

// --- Skills -----------------------------------------------------------------

function SkillsPanel({ name }: { name: string }) {
  const qc = useQueryClient();
  const skills = useQuery({ queryKey: ["skills", name], queryFn: () => api.listSkills(name) });
  const [selected, setSelected] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const body = useQuery({
    queryKey: ["skill", name, selected],
    queryFn: () => api.getSkill(name, selected!),
    enabled: !!selected,
  });
  const [text, setText] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (skill: string) => api.setSkill(name, skill, text ?? body.data?.body ?? ""),
    onSuccess: () => { toast.success("Skill saved"); qc.invalidateQueries({ queryKey: ["skills", name] }); },
    onError: err,
  });
  const remove = useMutation({
    mutationFn: (skill: string) => api.deleteSkill(name, skill),
    onSuccess: () => { setSelected(null); qc.invalidateQueries({ queryKey: ["skills", name] }); },
    onError: err,
  });

  return (
    <div className="grid grid-cols-[220px_1fr] gap-4">
      <Card>
        <CardHeader><CardTitle className="text-base">Skills</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            {skills.data?.map((s) => (
              <button
                key={s}
                onClick={() => { setSelected(s); setText(null); }}
                className={`block w-full rounded px-2 py-1 text-left text-sm ${selected === s ? "bg-primary/15 text-brand-amber" : "hover:bg-accent"}`}
              >
                {s}
              </button>
            ))}
            {skills.data?.length === 0 && <p className="text-sm text-muted-foreground">No skills.</p>}
          </div>
          <div className="flex gap-2">
            <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="new-skill" className="h-8" />
            <Button
              size="sm"
              onClick={() => { if (newName.trim()) { setSelected(newName.trim()); setText("---\nname: " + newName.trim() + "\ndescription: \n---\n"); setNewName(""); } }}
            >
              +
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">{selected ?? "Select a skill"}</CardTitle>
          {selected && (
            <Button size="sm" variant="ghost" onClick={() => remove.mutate(selected)}><Trash2 className="h-4 w-4" /></Button>
          )}
        </CardHeader>
        <CardContent className="space-y-4">
          {selected ? (
            <>
              <CodeEditor value={text ?? body.data?.body ?? ""} onChange={setText} language="markdown" height="360px" />
              <Button onClick={() => save.mutate(selected)} disabled={save.isPending}>Save SKILL.md</Button>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              Skills are delivered to the engine as <code className="text-brand-cyan">.claude/skills/&lt;name&gt;/SKILL.md</code> at run time.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
