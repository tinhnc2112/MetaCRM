import { apiClient } from "./apiClient";
import type {
  CustomerSegment,
  CustomerSegmentCustomersResponse,
  CustomerSegmentDeleteResponse,
  CustomerSegmentListResponse,
  CustomerSegmentPreviewResponse,
  CustomerSegmentUpsertInput
} from "../types/segment";

export async function listCustomerSegments(): Promise<CustomerSegmentListResponse> {
  const response = await apiClient.get<CustomerSegmentListResponse>("/api/v1/facebook/segments");
  return response.data;
}

export async function getCustomerSegment(segmentId: number): Promise<CustomerSegment> {
  const response = await apiClient.get<CustomerSegment>(`/api/v1/facebook/segments/${encodeURIComponent(String(segmentId))}`);
  return response.data;
}

export async function createCustomerSegment(input: CustomerSegmentUpsertInput): Promise<CustomerSegment> {
  const response = await apiClient.post<CustomerSegment>("/api/v1/facebook/segments", input);
  return response.data;
}

export async function updateCustomerSegment(
  segmentId: number,
  input: CustomerSegmentUpsertInput
): Promise<CustomerSegment> {
  const response = await apiClient.put<CustomerSegment>(
    `/api/v1/facebook/segments/${encodeURIComponent(String(segmentId))}`,
    input
  );
  return response.data;
}

export async function deleteCustomerSegment(segmentId: number): Promise<CustomerSegmentDeleteResponse> {
  const response = await apiClient.delete<CustomerSegmentDeleteResponse>(
    `/api/v1/facebook/segments/${encodeURIComponent(String(segmentId))}`
  );
  return response.data;
}

export async function listCustomerSegmentCustomers(
  segmentId: number,
  page?: number,
  pageSize?: number
): Promise<CustomerSegmentCustomersResponse> {
  const response = await apiClient.get<CustomerSegmentCustomersResponse>(
    `/api/v1/facebook/segments/${encodeURIComponent(String(segmentId))}/customers`,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}

export async function previewCustomerSegmentDefinition(
  input: CustomerSegmentUpsertInput,
  page?: number,
  pageSize?: number
): Promise<CustomerSegmentPreviewResponse> {
  const response = await apiClient.post<CustomerSegmentPreviewResponse>("/api/v1/facebook/segments/preview", input, {
    params: { page, page_size: pageSize }
  });
  return response.data;
}

export async function previewCustomerSegment(
  segmentId: number,
  page?: number,
  pageSize?: number
): Promise<CustomerSegmentPreviewResponse> {
  const response = await apiClient.post<CustomerSegmentPreviewResponse>(
    `/api/v1/facebook/segments/${encodeURIComponent(String(segmentId))}/preview`,
    undefined,
    { params: { page, page_size: pageSize } }
  );
  return response.data;
}
