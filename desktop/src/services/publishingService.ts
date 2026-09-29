import { apiClient } from "./apiClient";
import type { PublishingConfig, ScheduledPost } from "../types/publishing";

const root = "/api/v1/publishing";

export async function getPublishingConfig(): Promise<PublishingConfig> {
  return (await apiClient.get<PublishingConfig>(`${root}/config`)).data;
}

export async function savePublishingConfig(input: { spreadsheet_id: string; worksheet: string; timezone: string }) {
  return (await apiClient.put(`${root}/config`, input)).data;
}

export async function syncPublishingSheet(): Promise<Record<string, number>> {
  return (await apiClient.post<Record<string, number>>(`${root}/sync`)).data;
}

export async function listScheduledPosts(pageId?: string, status?: string): Promise<{ items: ScheduledPost[] }> {
  return (await apiClient.get<{ items: ScheduledPost[] }>(`${root}/posts`, {
    params: { page_id: pageId || undefined, status: status || undefined }
  })).data;
}

export async function cancelScheduledPost(id: string) {
  return (await apiClient.post(`${root}/posts/${id}/cancel`)).data;
}

export async function retryScheduledPost(id: string) {
  return (await apiClient.post(`${root}/posts/${id}/retry`)).data;
}

export async function reschedulePost(id: string, scheduledForUtc: string) {
  return (await apiClient.post(`${root}/posts/${id}/reschedule`, { scheduled_for_utc: scheduledForUtc })).data;
}

export async function resolvePost(id: string, outcome: "published" | "verified_not_published", facebookPostId?: string) {
  return (await apiClient.post(`${root}/posts/${id}/resolve`, {
    outcome, facebook_post_id: facebookPostId || null, confirmed: true
  })).data;
}
