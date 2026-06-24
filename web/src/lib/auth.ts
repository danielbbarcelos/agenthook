// Admin token kept in sessionStorage (cleared when the tab closes). The token
// is sent as a bearer header on every /admin request. The panel must run on
// localhost — the server's loopback gate refuses non-127.0.0.1 callers unless
// admin_remote is enabled.

const KEY = "agenthook.adminToken";

export function getToken(): string | null {
  return sessionStorage.getItem(KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(KEY);
}
