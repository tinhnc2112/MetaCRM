import { apiClient } from "./apiClient";
import type {
  CurrentFacebookPageResponse,
  FacebookAuthUrlResponse,
  FacebookPageListResponse
} from "../types/facebook";

export async function getFacebookAuthUrl(): Promise<FacebookAuthUrlResponse> {
  const response = await apiClient.get<FacebookAuthUrlResponse>("/api/v1/facebook/auth/url");
  return response.data;
}

export async function syncFacebookPages(): Promise<FacebookPageListResponse> {
  const response = await apiClient.post<FacebookPageListResponse>("/api/v1/facebook/pages/sync");
  return response.data;
}

export async function getFacebookPages(): Promise<FacebookPageListResponse> {
  const response = await apiClient.get<FacebookPageListResponse>("/api/v1/facebook/pages");
  return response.data;
}

export async function getCurrentFacebookPage(): Promise<CurrentFacebookPageResponse> {
  const response = await apiClient.get<CurrentFacebookPageResponse>("/api/v1/facebook/pages/current");
  return response.data;
}

export async function selectFacebookPage(pageId: string): Promise<CurrentFacebookPageResponse> {
  const response = await apiClient.post<CurrentFacebookPageResponse>(
    `/api/v1/facebook/pages/${encodeURIComponent(pageId)}/select`
  );
  return response.data;
}
