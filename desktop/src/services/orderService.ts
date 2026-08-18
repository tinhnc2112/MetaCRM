import { apiClient } from "./apiClient";
import type {
  CustomerOrderSummary,
  OrderCreatePayload,
  OrderListResponse,
  OrderResponse,
  OrderStatus,
  OrderUpdatePayload
} from "../types/order";

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

export async function getOrder(orderUuid: string): Promise<OrderResponse> {
  const response = await apiClient.get<OrderResponse>(`/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}`);
  return response.data;
}

export async function getCustomerOrderSummary(customerUuid: string): Promise<CustomerOrderSummary> {
  const response = await apiClient.get<CustomerOrderSummary>(
    `/api/v1/facebook/customers/${encodeURIComponent(customerUuid)}/orders/summary`
  );
  return response.data;
}

export async function createOrder(payload: OrderCreatePayload): Promise<OrderResponse> {
  const response = await apiClient.post<OrderResponse>("/api/v1/facebook/orders", payload);
  return response.data;
}

export async function updateOrder(orderUuid: string, payload: OrderUpdatePayload): Promise<OrderResponse> {
  const response = await apiClient.patch<OrderResponse>(
    `/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}`,
    payload
  );
  return response.data;
}
