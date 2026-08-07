import axios from "axios";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL,
  timeout: 15000,
  headers: {
    "Content-Type": "application/json"
  }
});
