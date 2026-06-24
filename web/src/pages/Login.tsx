import { Zap } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
      const msg =
        err instanceof ApiError && err.status === 403
          ? "Loopback-only: the server refuses non-localhost callers. Set admin_remote: true to allow remote access."
          : "Invalid admin token.";
      setError(msg);
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-2 flex items-center gap-2">
            <Zap className="h-6 w-6 text-brand-amber" fill="currentColor" />
            <span className="text-xl font-bold">agenthook</span>
          </div>
          <CardTitle>Admin panel</CardTitle>
          <CardDescription>
            Paste the admin token to manage this agenthook. Find it with{" "}
            <code className="text-brand-cyan">agenthook</code> config or in{" "}
            <code className="text-brand-cyan">~/.agenthook/config.yaml</code> (admin_token).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="token">Admin token</Label>
              <Input
                id="token"
                type="password"
                autoFocus
                value={token}
                onChange={(e) => setTok(e.target.value)}
                placeholder="••••••••••••"
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={!token.trim() || busy}>
              {busy ? "Checking…" : "Enter"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
