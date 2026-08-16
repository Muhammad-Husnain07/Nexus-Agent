/**
 * Legacy import path — re-exports THE single API transport (src/api/client).
 * Existing hooks keep working; all new code imports from src/api directly.
 */
export { api, get, post, put, patch, del, normalizeError } from "../api/client";
export type { ApiError } from "../types/api";
export { default } from "../api/client";
