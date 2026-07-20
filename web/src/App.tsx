import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { api } from "./lib/api";
import { isAuthed } from "./lib/auth";
import { Config } from "./pages/Config";
import { Dashboard } from "./pages/Dashboard";
import { InstanceDetail } from "./pages/InstanceDetail";
import { Instances } from "./pages/Instances";
import { JobDetail } from "./pages/JobDetail";
import { Jobs } from "./pages/Jobs";
import { Login } from "./pages/Login";
import { Sessions } from "./pages/Sessions";
import { Usage } from "./pages/Usage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  // Optimistic: if we still hold a csrf we assume the cookie is live (a stray 401
  // bounces to /login anyway). Otherwise probe /ui/session once to rehydrate a
  // cookie that survived a reload but lost the in-tab csrf.
  const [state, setState] = useState<"checking" | "authed" | "anon">(isAuthed() ? "authed" : "checking");
  useEffect(() => {
    if (state === "checking") api.session().then((ok) => setState(ok ? "authed" : "anon"));
  }, [state]);
  if (state === "checking") return null;
  if (state === "anon") return <Navigate to="/login" replace />;
  return <AppShell>{children}</AppShell>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/instances" element={<RequireAuth><Instances /></RequireAuth>} />
      <Route path="/instances/:name" element={<RequireAuth><InstanceDetail /></RequireAuth>} />
      <Route path="/jobs" element={<RequireAuth><Jobs /></RequireAuth>} />
      <Route path="/jobs/:id" element={<RequireAuth><JobDetail /></RequireAuth>} />
      <Route path="/sessions" element={<RequireAuth><Sessions /></RequireAuth>} />
      <Route path="/usage" element={<RequireAuth><Usage /></RequireAuth>} />
      <Route path="/config" element={<RequireAuth><Config /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
