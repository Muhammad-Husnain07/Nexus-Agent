import axios from "axios";
import { enqueueSnackbar } from "notistack";
import { useAuthStore } from "../stores/auth-store";

const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const { access_token, selectedTenantId } = useAuthStore.getState();
  if (access_token) config.headers.Authorization = `Bearer ${access_token}`;
  if (selectedTenantId) config.headers["X-Tenant-ID"] = selectedTenantId;
  return config;
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (err: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null) => {
  failedQueue.forEach((p) => (token ? p.resolve(token) : p.reject(error)));
  failedQueue = [];
};

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        });
      }
      originalRequest._retry = true;
      isRefreshing = true;
      try {
        const { refresh_token } = useAuthStore.getState();
        if (!refresh_token) throw new Error("No refresh token");
        const res = await axios.post("/api/v1/auth/refresh", { refresh_token });
        const { access_token, refresh_token: newRefresh } = res.data;
        useAuthStore.getState().setTokens(access_token, newRefresh);
        processQueue(null, access_token);
        originalRequest.headers.Authorization = `Bearer ${access_token}`;
        return api(originalRequest);
      } catch (err) {
        processQueue(err, null);
        useAuthStore.getState().logout();
        window.location.href = "/login";
        return Promise.reject(err);
      } finally {
        isRefreshing = false;
      }
    }
    if (error.response?.status === 403) {
      enqueueSnackbar("Access denied. You do not have permission.", {
        variant: "error",
      });
    }
    return Promise.reject(error);
  }
);

export default api;
