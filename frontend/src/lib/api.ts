import axios from "axios";

const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.error?.message || err.message;
    console.error(`API Error [${err.response?.status}]:`, msg);
    return Promise.reject(err);
  }
);

export default api;
