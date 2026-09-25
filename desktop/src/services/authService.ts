import { apiClient } from "./apiClient";
import type { AuthTokens, LoginRequest } from "../types/auth";

export async function login(request: LoginRequest): Promise<AuthTokens> {
  const response = await apiClient.post<AuthTokens>("/api/v1/auth/login", request);
  return response.data;
}

export async function logout(refreshToken: string): Promise<void> {
  await apiClient.post("/api/v1/auth/logout", { refresh_token: refreshToken });
}
