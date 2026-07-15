import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Brand } from "@/components/Brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

export function Login() {
  const nav = useNavigate();
  const [token, setTok] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setToken(token.trim());
    try {
      await api.ping();
      nav("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "This agenthook only answers localhost. Open the panel on the same machine, or set admin_remote: true in config.yaml."
          : "That token didn't work. Check admin_token in config.yaml and try again.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex justify-center">
          <Brand status="unknown" />
        </div>
        <Card>
          <CardContent className="pt-6">
            <h1 className="text-lg font-bold tracking-tight">Sign in</h1>
            <p className="mb-5 mt-1 text-sm text-muted-foreground">
              Paste your admin token to manage this agenthook.
            </p>
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="token">Admin token</Label>
                <Input
                  id="token"
                  type="password"
                  autoFocus
                  autoComplete="off"
                  value={token}
                  onChange={(e) => setTok(e.target.value)}
                  placeholder="••••••••••••••••"
                  className="font-mono"
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={!token.trim() || busy}>
                {busy ? "Checking…" : "Sign in"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          Find it with{" "}
          <code className="font-mono text-foreground">grep admin_token ~/.agenthook/config.yaml</code>
        </p>
      </div>
    </div>
  );
}
