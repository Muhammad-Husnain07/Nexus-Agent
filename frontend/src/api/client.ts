/**
 * THE single API transport layer. No component calls fetch/axios/WebSocket
 * directly — only src/api/ owns transport (FE plan immutable rule).
 *
 * - request interceptor: auth headers (auth-store) + X-Request-Id correlation
 * - response interceptor: normalizes EVERY failure to ApiError
 *   {code, message, request_id, status} (reads backend {error:{...}},
 *   then {detail}, then error_code)
 */
import axios, { AxiosError } from "axios";

import type { ApiError, BackendErrorBody } from "../types/api";
import { getAuthHeaders } from "./auth-store";

export const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  config.headers.set("X-Request-Id", crypto.randomUUID());
  const authHeaders = getAuthHeaders();
  for (const [k, v] of Object.entries(authHeaders)) {
    config.headers.set(k, v);
  }
  return config;
});

export function normalizeError(err: unknown): ApiError {
  if (axios.isAxiosError(err)) {
    const axiosErr = err as AxiosError<BackendErrorBody>;
    const status = axiosErr.response?.status;
    const body = axiosErr.response?.data;
    const wrapped = body?.error;
    return {
      code: wrapped?.code ?? body?.error_code ?? _codeForStatus(status),
      message:
        wrapped?.message ??
        body?.detail ??
        axiosErr.message ??
        "Request failed",
      request_id: wrapped?.request_id,
      status,
    };
  }
  return {
    code: "INTERNAL_ERROR",
    message: err instanceof Error ? err.message : "Unknown error",
  };
}

function _codeForStatus(status: number | undefined): string {
  if (status === 401) return "UNAUTHORIZED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 409) return "CONFLICT";
  if (status === 422) return "VALIDATION_ERROR";
  if (status === 429) return "RATE_LIMITED";
  if (status && status >= 500) return "INTERNAL_ERROR";
  return "REQUEST_FAILED";
}

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const normalized = normalizeError(err);
    console.error(
      `API Error [${normalized.status ?? "?"}] ${normalized.code}: ${normalized.message}`,
    );
    return Promise.reject(normalized);
  },
);

/** Typed helpers — components/hooks use these, never axios directly. */
export async function get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const res = await api.get<T>(path, { params });
  return res.data;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await api.post<T>(path, body);
  return res.data;
}

export async function put<T>(path: string, body?: unknown): Promise<T> {
  const res = await api.put<T>(path, body);
  return res.data;
}

export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const res = await api.patch<T>(path, body);
  return res.data;
}

export async function del<T = void>(path: string): Promise<T> {
  const res = await api.delete<T>(path);
  return res.data;
}

export { axios };
export default api;
