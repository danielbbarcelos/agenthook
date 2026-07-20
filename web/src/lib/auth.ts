// Session-based auth for the native UI. The session itself is an HttpOnly cookie
// (invisible to JS) set by POST /ui/login; here we keep only the CSRF token, which
// the API layer echoes in X-Agenthook-CSRF on unsafe requests. The panel must run
// on localhost unless admin_remote is enabled server-side.

const CSRF_KEY = "agenthook.csrf";

export function getCsrf(): string | null {
  return sessionStorage.getItem(CSRF_KEY);
}

export function setCsrf(csrf: string): void {
  sessionStorage.setItem(CSRF_KEY, csrf);
}

export function clearCsrf(): void {
  sessionStorage.removeItem(CSRF_KEY);
}

export function isAuthed(): boolean {
  return !!sessionStorage.getItem(CSRF_KEY);
}
