import { clearCsrf, getCsrf, setCsrf } from "./auth";
import type {
  AuditRow,
  Config,
  CreateInstanceResult,
  EngineAuthStatus,
  EngineInfo,
  EngineLoginStart,
  EnvVar,
  Guardrails,
  Instance,
  InstanceSummary,
  Job,
  RepoView,
  Session,
  UsageSummary,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  // Auth rides the HttpOnly session cookie; unsafe methods must also carry the
  // session's CSRF token (cookies are auto-sent, this header is not).
  const csrf = getCsrf();
  if (csrf && method !== "GET") headers["X-Agenthook-CSRF"] = csrf;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(path, {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    clearCsrf();
    if (!location.hash.includes("/login")) location.assign("/ui/#/login");
    throw new ApiError(401, "unauthorized — please sign in again");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail ?? data);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  // native-UI session auth (human plane)
  login: async (username: string, password: string, totp?: string): Promise<{ username: string; csrf: string }> => {
    const res = await fetch("/ui/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, ...(totp ? { totp } : {}) }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new ApiError(res.status, (data?.error as string) ?? "login failed");
    }
    const data = await res.json();
    setCsrf(data.csrf);
    return data;
  },
  logout: async (): Promise<void> => {
    try {
      await fetch("/ui/logout", { method: "POST", credentials: "include" });
    } catch {
      /* best-effort */
    }
    clearCsrf();
  },
  // rehydrate an existing cookie session (e.g. after a page reload cleared csrf)
  session: async (): Promise<boolean> => {
    try {
      const res = await fetch("/ui/session", { credentials: "include" });
      if (!res.ok) return false;
      const data = await res.json();
      if (data?.csrf) setCsrf(data.csrf);
      return !!data?.authenticated;
    } catch {
      return false;
    }
  },

  // liveness — public endpoint, drives the sidebar server status chip
  health: async (): Promise<{ ok: boolean }> => {
    const res = await fetch("/healthz");
    if (!res.ok) throw new ApiError(res.status, "server down");
    return res.json();
  },

  // engines
  listEngines: () => request<EngineInfo[]>("GET", "/admin/engines"),

  // instances
  listInstances: () => request<InstanceSummary[]>("GET", "/admin/instances"),
  getInstance: (name: string) => request<Instance>("GET", `/admin/instances/${name}`),
  createInstance: (body: Record<string, unknown>) =>
    request<CreateInstanceResult>("POST", "/admin/instances", body),
  patchInstance: (name: string, body: Record<string, unknown>) =>
    request<Instance>("PATCH", `/admin/instances/${name}`, body),
  deleteInstance: (name: string) => request<void>("DELETE", `/admin/instances/${name}`),
  pauseInstance: (name: string, reason?: string) =>
    request<InstanceSummary>("POST", `/admin/instances/${name}/pause`, { reason }),
  resumeInstance: (name: string) => request<InstanceSummary>("POST", `/admin/instances/${name}/resume`),

  // repos
  listRepos: (name: string) => request<RepoView[]>("GET", `/admin/instances/${name}/repos`),
  addRepo: (name: string, body: { url: string; name?: string; branch_base?: string }) =>
    request<RepoView[]>("POST", `/admin/instances/${name}/repos`, body),
  removeRepo: (name: string, repo: string) =>
    request<RepoView[]>("DELETE", `/admin/instances/${name}/repos/${repo}`),

  // env
  listEnv: (name: string) => request<EnvVar[]>("GET", `/admin/instances/${name}/env`),
  setEnv: (name: string, key: string, body: { value: string; secret: boolean }) =>
    request<EnvVar>("PUT", `/admin/instances/${name}/env/${key}`, body),
  deleteEnv: (name: string, key: string) =>
    request<void>("DELETE", `/admin/instances/${name}/env/${key}`),

  // engine auth (the coding engine's own login; status + logout only)
  getEngineAuth: (name: string) =>
    request<EngineAuthStatus>("GET", `/admin/instances/${name}/engine-auth`),
  logoutEngineAuth: (name: string) =>
    request<void>("DELETE", `/admin/instances/${name}/engine-auth`),
  startEngineLogin: (name: string) =>
    request<EngineLoginStart>("POST", `/admin/instances/${name}/engine-auth/login/start`),
  submitEngineLoginCode: (name: string, body: { session: string; code: string }) =>
    request<{ authenticated: boolean }>("POST", `/admin/instances/${name}/engine-auth/login/code`, body),

  // config blocks
  setAuth: (name: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>("PUT", `/admin/instances/${name}/auth`, body),
  setVerify: (name: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>("PUT", `/admin/instances/${name}/verify`, body),
  setMcp: (name: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>("PUT", `/admin/instances/${name}/mcp`, body),
  getContext: (name: string) => request<{ body: string }>("GET", `/admin/instances/${name}/context`),
  setContext: (name: string, body: string) =>
    request<{ body: string }>("PUT", `/admin/instances/${name}/context`, { body }),
  setTemplate: (name: string, rtype: string, body: string) =>
    request<{ request_type: string; body: string }>(
      "PUT",
      `/admin/instances/${name}/templates/${rtype}`,
      { body },
    ),
  deleteTemplate: (name: string, rtype: string) =>
    request<void>("DELETE", `/admin/instances/${name}/templates/${rtype}`),

  // guardrails (append-only)
  getGuardrails: (name: string) => request<Guardrails>("GET", `/admin/instances/${name}/guardrails`),
  setGuardrails: (name: string, body: Guardrails) =>
    request<Guardrails>("PUT", `/admin/instances/${name}/guardrails`, body),

  // skills
  listSkills: (name: string) => request<string[]>("GET", `/admin/instances/${name}/skills`),
  getSkill: (name: string, skill: string) =>
    request<{ name: string; body: string }>("GET", `/admin/instances/${name}/skills/${skill}`),
  setSkill: (name: string, skill: string, body: string) =>
    request<{ name: string; body: string }>("PUT", `/admin/instances/${name}/skills/${skill}`, { body }),
  deleteSkill: (name: string, skill: string) =>
    request<void>("DELETE", `/admin/instances/${name}/skills/${skill}`),

  // global config
  getConfig: () => request<Config>("GET", "/admin/config"),
  patchConfig: (body: Record<string, unknown>) => request<Config>("PATCH", "/admin/config", body),

  // observability
  listJobs: (params: { instance?: string; status?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.instance) q.set("instance", params.instance);
    if (params.status) q.set("status", params.status);
    q.set("limit", String(params.limit ?? 100));
    return request<Job[]>("GET", `/admin/jobs?${q}`);
  },
  getJob: (id: string) => request<Job>("GET", `/admin/jobs/${id}`),
  listSessions: (instance?: string) =>
    request<Session[]>("GET", `/admin/sessions${instance ? `?instance=${instance}` : ""}`),
  usage: (instance?: string) =>
    request<UsageSummary>("GET", `/admin/usage${instance ? `?instance=${instance}` : ""}`),
  audit: (params: { instance?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.instance) q.set("instance", params.instance);
    q.set("limit", String(params.limit ?? 200));
    return request<AuditRow[]>("GET", `/admin/audit?${q}`);
  },
};
