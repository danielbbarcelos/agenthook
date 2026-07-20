import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Brand } from "@/components/Brand";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";

export function Login() {
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [needTotp, setNeedTotp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(username.trim(), password, needTotp ? totp.trim() : undefined);
      nav("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.message === "totp_required") {
        setNeedTotp(true);
        setError("Enter the code from your authenticator app.");
      } else if (err instanceof ApiError && err.status === 403) {
        setError(
          "This agenthook only answers localhost. Open the panel on the same machine, or set admin_remote in config.yaml.",
        );
      } else {
        setError("Invalid username or password.");
      }
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
            <p className="mb-5 mt-1 text-sm text-muted-foreground">Sign in to manage this agenthook.</p>
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  autoFocus
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {needTotp && (
                <div className="space-y-2">
                  <Label htmlFor="totp">Authenticator code</Label>
                  <Input
                    id="totp"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={totp}
                    onChange={(e) => setTotp(e.target.value)}
                    placeholder="123456"
                    className="font-mono"
                  />
                </div>
              )}
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={!username.trim() || !password || busy}>
                {busy ? "Signing in…" : "Sign in"}
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="mt-4 text-center text-xs text-muted-foreground">
          No account yet? Create one on the host:{" "}
          <code className="font-mono text-foreground">agenthook admin create-user &lt;name&gt;</code>
        </p>
      </div>
    </div>
  );
}
