import { apiClient } from "./apiClient";
import type {
  CarrierOperationListResponse,
  CustomerOrderSummary,
  OrderCreatePayload,
  OrderListFilters,
  OrderListResponse,
  OrderOperationalSummary,
  OrderResponse,
  OrderStatus,
  OrderTimelineResponse,
  OrderUpdatePayload,
  Shipment,
  ShipmentListResponse,
  ShipmentStatus,
  ShipmentWaybillResponse,
  ShipmentTrackingPayload,
  ShippingDestinationInput
} from "../types/order";

export async function listOrders(input?: OrderListFilters): Promise<OrderListResponse> {
  const response = await apiClient.get<OrderListResponse>("/api/v1/facebook/orders", {
    params: {
      page: input?.page,
      page_size: input?.pageSize,
      q: input?.search,
      queue: input?.queue,
      status: input?.orderStatus,
      payment_status: input?.paymentStatus,
      shipping_status: input?.shippingStatus
    }
  });
  return response.data;
}

export async function getOrderOperationalSummary(): Promise<OrderOperationalSummary> {
  const response = await apiClient.get<OrderOperationalSummary>(
    "/api/v1/facebook/orders/operational-summary"
  );
  return response.data;
}

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

export async function getOrderTimeline(orderUuid: string): Promise<OrderTimelineResponse> {
  const response = await apiClient.get<OrderTimelineResponse>(
    `/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}/timeline`
  );
  return response.data;
}

export async function getCustomerOrderSummary(customerUuid: string): Promise<CustomerOrderSummary> {
  const response = await apiClient.get<CustomerOrderSummary>(
    `/api/v1/facebook/customers/${encodeURIComponent(customerUuid)}/orders/summary`
  );
  return response.data;
}

export async function createOrder(
  payload: OrderCreatePayload,
  idempotencyKey: string
): Promise<OrderResponse> {
  const response = await apiClient.post<OrderResponse>("/api/v1/facebook/orders", payload, {
    headers: { "Idempotency-Key": idempotencyKey }
  });
  return response.data;
}

export async function updateOrder(orderUuid: string, payload: OrderUpdatePayload): Promise<OrderResponse> {
  const response = await apiClient.patch<OrderResponse>(
    `/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}`,
    payload
  );
  return response.data;
}

export async function updateOrderShippingDestination(
  orderUuid: string,
  payload: ShippingDestinationInput
): Promise<OrderResponse> {
  const response = await apiClient.patch<OrderResponse>(
    `/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}/shipping-address`,
    payload
  );
  return response.data;
}

export async function listOrderShipments(orderUuid: string): Promise<ShipmentListResponse> {
  const response = await apiClient.get<ShipmentListResponse>(
    `/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}/shipments`
  );
  return response.data;
}

export async function createOrderShipment(orderUuid: string): Promise<Shipment> {
  const response = await apiClient.post<Shipment>(
    `/api/v1/facebook/orders/${encodeURIComponent(orderUuid)}/shipments`
  );
  return response.data;
}

export async function getShipmentWaybill(shipmentUuid: string): Promise<ShipmentWaybillResponse> {
  const response = await apiClient.get<ShipmentWaybillResponse>(
    `/api/v1/facebook/shipments/${encodeURIComponent(shipmentUuid)}/waybill`
  );
  return response.data;
}

export async function listShipmentCarrierOperations(
  shipmentUuid: string
): Promise<CarrierOperationListResponse> {
  const response = await apiClient.get<CarrierOperationListResponse>(
    `/api/v1/facebook/shipments/${encodeURIComponent(shipmentUuid)}/carrier-operations`
  );
  return response.data;
}

export async function updateShipmentStatus(
  shipmentUuid: string,
  status: ShipmentStatus
): Promise<Shipment> {
  const response = await apiClient.patch<Shipment>(
    `/api/v1/facebook/shipments/${encodeURIComponent(shipmentUuid)}/status`,
    { status }
  );
  return response.data;
}

export async function updateShipmentTracking(
  shipmentUuid: string,
  payload: ShipmentTrackingPayload
): Promise<Shipment> {
  const response = await apiClient.patch<Shipment>(
    `/api/v1/facebook/shipments/${encodeURIComponent(shipmentUuid)}/tracking`,
    payload
  );
  return response.data;
}
