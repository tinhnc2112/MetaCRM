import { apiClient } from "./apiClient";
import type { AuthTokens, LoginRequest } from "../types/auth";

export async function login(request: LoginRequest): Promise<AuthTokens> {
  const response = await apiClient.post<AuthTokens>("/api/v1/auth/login", request);
  return response.data;
}
