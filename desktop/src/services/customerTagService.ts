import { apiClient } from "./apiClient";
import type {
  CustomerTag,
  CustomerTagAssignmentResponse,
  CustomerTagCustomersResponse,
  CustomerTagListResponse,
} from "../types/customer";

export async function listCustomerTags(): Promise<CustomerTagListResponse> {
  const response = await apiClient.get<CustomerTagListResponse>("/api/v1/facebook/customer-tags");
  return response.data;
}

export async function createCustomerTag(input: {
  name: string;
  description: string | null;
}): Promise<CustomerTag> {
  const response = await apiClient.post<CustomerTag>("/api/v1/facebook/customer-tags", input);
  return response.data;
}

export async function updateCustomerTag(
  tagId: number,
  input: { name: string; description: string | null }
): Promise<CustomerTag> {
  const response = await apiClient.patch<CustomerTag>(
    `/api/v1/facebook/customer-tags/${encodeURIComponent(String(tagId))}`,
    input
  );
  return response.data;
}

export async function deleteCustomerTag(tagId: number): Promise<{ deleted: boolean; tag_id: number }> {
  const response = await apiClient.delete<{ deleted: boolean; tag_id: number }>(
    `/api/v1/facebook/customer-tags/${encodeURIComponent(String(tagId))}`
  );
  return response.data;
}

export async function listCustomerTagCustomers(
  tagId: number,
  page?: number,
  pageSize?: number
): Promise<CustomerTagCustomersResponse> {
  const response = await apiClient.get<CustomerTagCustomersResponse>(
    `/api/v1/facebook/customer-tags/${encodeURIComponent(String(tagId))}/customers`,
    {
      params: { page, page_size: pageSize }
    }
  );
  return response.data;
}

export async function assignCustomerTag(
  conversationId: string,
  tagId: number
): Promise<CustomerTagAssignmentResponse> {
  const response = await apiClient.post<CustomerTagAssignmentResponse>(
    `/api/v1/facebook/customers/${encodeURIComponent(conversationId)}/tags/${encodeURIComponent(String(tagId))}`
  );
  return response.data;
}

export async function removeCustomerTag(
  conversationId: string,
  tagId: number
): Promise<CustomerTagAssignmentResponse> {
  const response = await apiClient.delete<CustomerTagAssignmentResponse>(
    `/api/v1/facebook/customers/${encodeURIComponent(conversationId)}/tags/${encodeURIComponent(String(tagId))}`
  );
  return response.data;
}
