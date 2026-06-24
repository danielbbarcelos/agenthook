// Types mirroring the agenthook Management API shapes
// (agenthook/api_models.py + admin_api.py + serde.py).

export interface InstanceSummary {
  name: string;
  engine: string;
  deliverable: string;
  repos: string[];
  paused: boolean;
}

export interface Guardrails {
  extra?: string;
  force_read_only?: boolean;
}

export interface Instance {
  name: string;
  engine: string;
  repo: string | null;
  repos: RepoEntry[];
  branch_base: string;
  engine_auth: string;
  webhook_auth: Record<string, unknown>;
  model: string | null;
  default_prompt: string | null;
  deliverable: string;
  on_result: string[];
  callback_url: string | null;
  pr_branch: string;
  allow_overrides: string[];
  limits: Record<string, unknown>;
  verify: Record<string, unknown>;
  mcp: Record<string, unknown>;
  schedules: Record<string, unknown>[];
  secrets_backend: string;
  context_template: string | null;
  templates: Record<string, string>;
  guardrails: Guardrails;
  skills: Record<string, string>;
  paused: boolean;
  paused_reason: string | null;
  key_fingerprint: string | null;
}

export interface RepoEntry {
  url: string;
  name?: string;
  branch_base?: string;
}

export interface RepoView {
  name: string;
  url: string;
  branch_base: string;
}

export interface CreateInstanceResult {
  instance: Instance;
  encryption_key: string;
  fingerprint: string;
}

export interface EnvVar {
  name: string;
  value: string;
  secret: boolean;
}

export interface Job {
  id: string;
  instance: string;
  status: string;
  deliverable: string;
  mode: string;
  session_id: string | null;
  thread_key: string | null;
  prompt?: string;
  error_class?: string | null;
  error_message?: string | null;
  pr_url?: string | null;
  result?: { text?: string } | null;
  usage?: Record<string, unknown>;
  attempts?: number;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface Session {
  id: string;
  instance: string;
  thread_key: string;
  status: string;
  job_count: number;
  description?: string | null;
  created_at: number;
  updated_at: number;
}

export interface UsageSummary {
  jobs: number;
  cost_usd: number;
}

export interface AuditRow {
  id: number;
  job_id: string;
  instance: string;
  requester?: string | null;
  request_type?: string | null;
  deliverable?: string | null;
  status?: string | null;
  error_class?: string | null;
  cost_usd?: number | null;
  created_at: number;
}

export interface Config {
  host: string;
  port: number;
  workers: number;
  default_concurrency: number;
  retention: string;
  truncate_chars: number;
  approval_ttl_s: number;
  public_base_url: string;
  approval_secret: string;
  admin_token: string;
  admin_remote: boolean;
  use_docker: boolean;
  docker_image: string;
  [key: string]: unknown;
}
