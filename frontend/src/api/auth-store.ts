/**
 * Credential store for api_key / jwt auth modes (backend default: none).
 * The client attaches headers via getAuthHeaders() — no component touches
 * credentials directly. No login UX until auth mode is actually enabled.
 */

const TOKEN_KEY = "nexus_auth_token";
const API_KEY_KEY = "nexus_api_key";

export function getStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredApiKey(): string | null {
  try {
    return localStorage.getItem(API_KEY_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable — auth headers just won't attach */
  }
}

export function setStoredApiKey(key: string | null): void {
  try {
    if (key) localStorage.setItem(API_KEY_KEY, key);
    else localStorage.removeItem(API_KEY_KEY);
  } catch {
    /* noop */
  }
}

/** Headers the API client attaches on every request (auth mode aware). */
export function getAuthHeaders(): Record<string, string> {
  const token = getStoredToken();
  if (token) return { Authorization: `Bearer ${token}` };
  const apiKey = getStoredApiKey();
  if (apiKey) return { "X-API-Key": apiKey };
  return {};
}
