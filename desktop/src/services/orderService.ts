import { apiClient } from "./apiClient";
import type { OrderListResponse, OrderStatus } from "../types/order";

export async function listCustomerOrders(
  customerUuid: string,
  input?: {
    page?: number;
    pageSize?: number;
    status?: OrderStatus;
  }
): Promise<OrderListResponse> {
  const response = await apiClient.get<OrderListResponse>(
    `/api/v1/facebook/customers/${encodeURIComponent(customerUuid)}/orders`,
    {
      params: {
        page: input?.page,
        page_size: input?.pageSize,
        status: input?.status
      }
    }
  );
  return response.data;
}
