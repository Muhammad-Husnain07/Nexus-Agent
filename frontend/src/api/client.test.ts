import { describe, expect, it } from "vitest";

import { normalizeError } from "./client";

describe("error normalization (backend shapes -> ApiError)", () => {
  const axiosError = (response?: unknown) => {
    const err = new Error("Request failed with status code 403") as Error & {
      isAxiosError?: boolean;
      response?: unknown;
    };
    err.isAxiosError = true;
    err.response = response;
    return err;
  };

  it("reads the backend {error:{code,message,request_id}} shape", () => {
    const apiError = normalizeError(
      axiosError({
        status: 500,
        data: {
          error: {
            code: "PLANNING_FAILED",
            message: "no executable plan",
            request_id: "req-123",
          },
        },
      }),
    );
    expect(apiError.code).toBe("PLANNING_FAILED");
    expect(apiError.message).toBe("no executable plan");
    expect(apiError.request_id).toBe("req-123");
    expect(apiError.status).toBe(500);
  });

  it("falls back to {detail} (HTTPException shape)", () => {
    const apiError = normalizeError(
      axiosError({ status: 403, data: { detail: "This session belongs to another user" } }),
    );
    expect(apiError.message).toBe("This session belongs to another user");
    expect(apiError.code).toBe("FORBIDDEN");
    expect(apiError.status).toBe(403);
  });

  it("falls back to {error_code} (rate-limit shape)", () => {
    const apiError = normalizeError(
      axiosError({ status: 429, data: { detail: "Rate limit exceeded", error_code: "RATE_LIMITED" } }),
    );
    expect(apiError.code).toBe("RATE_LIMITED");
    expect(apiError.message).toBe("Rate limit exceeded");
  });

  it("maps status codes for empty bodies", () => {
    expect(normalizeError(axiosError({ status: 401 })).code).toBe("UNAUTHORIZED");
    expect(normalizeError(axiosError({ status: 404 })).code).toBe("NOT_FOUND");
    expect(normalizeError(axiosError({ status: 422 })).code).toBe("VALIDATION_ERROR");
    expect(normalizeError(axiosError({ status: 503 })).code).toBe("INTERNAL_ERROR");
  });

  it("handles non-axios errors", () => {
    const apiError = normalizeError(new TypeError("boom"));
    expect(apiError.code).toBe("INTERNAL_ERROR");
    expect(apiError.message).toBe("boom");
  });
});
