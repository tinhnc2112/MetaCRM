import { apiClient } from "./apiClient";
import type { CustomerDuplicateListResponse, CustomerMergeRequest, CustomerMergeResponse } from "../types/customer";

export async function listCustomerDuplicates(page?: number, pageSize?: number): Promise<CustomerDuplicateListResponse> {
  const response = await apiClient.get<CustomerDuplicateListResponse>("/api/v1/facebook/customers/duplicates", {
    params: { page, page_size: pageSize }
  });
  return response.data;
}

export async function mergeCustomers(
  primaryCustomerId: string,
  input: CustomerMergeRequest
): Promise<CustomerMergeResponse> {
  const response = await apiClient.post<CustomerMergeResponse>(
    `/api/v1/facebook/customers/${encodeURIComponent(primaryCustomerId)}/merge`,
    input
  );
  return response.data;
}
