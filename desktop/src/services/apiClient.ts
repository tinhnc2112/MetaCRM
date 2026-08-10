import axios from "axios";

import { useAuthStore } from "../stores/authStore";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json"
  }
});

apiClient.interceptors.request.use((config) => {
  const session = useAuthStore.getState().session;
  if (session?.accessToken) {
    config.headers.Authorization = `Bearer ${session.accessToken}`;
  }
  return config;
});
