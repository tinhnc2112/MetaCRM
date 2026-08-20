import type { PaginationMeta } from "./messenger";

export type OrderStatus = "draft" | "confirmed" | "cancelled";
export type PaymentStatus = "unpaid" | "partial" | "paid" | "refunded";
export type ShippingStatus = "pending" | "packed" | "shipped" | "delivered" | "cancelled";
export type ShipmentStatus = "ready" | "packed" | "shipped" | "delivered" | "cancelled";
export type OrderOperationalQueue =
  | "draft"
  | "needs_payment"
  | "needs_packing"
  | "packed"
  | "in_transit"
  | "shipping_issue"
  | "cancelled";
export type OrderQueueSelection = "all" | OrderOperationalQueue;

export type OrderItem = {
  uuid: string;
  product_uuid: string | null;
  item_name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
  line_total: string;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type ManualOrderItemCreate = {
  product_uuid?: null;
  item_name: string;
  sku?: string | null;
  quantity: number;
  unit_price: number;
  note?: string | null;
};

export type ProductOrderItemCreate = {
  product_uuid: string;
  quantity: number;
  unit_price?: number;
  note?: string | null;
};

export type OrderItemCreate = ManualOrderItemCreate | ProductOrderItemCreate;

export type ShippingDestinationInput = {
  recipient_name?: string | null;
  recipient_phone?: string | null;
  address_line?: string | null;
  ward?: string | null;
  district?: string | null;
  province?: string | null;
  postal_code?: string | null;
  country_code?: string | null;
  note?: string | null;
};

export type ShippingDestination = {
  recipient_name: string | null;
  recipient_phone: string | null;
  address_line: string | null;
  ward: string | null;
  district: string | null;
  province: string | null;
  postal_code: string | null;
  country_code: string;
  note: string | null;
  is_complete: boolean;
};

export type ShipmentRecipient = {
  recipient_name: string;
  recipient_phone: string;
  address_line: string;
  ward: string;
  district: string;
  province: string;
  postal_code: string | null;
  country_code: string;
  delivery_note: string | null;
};

export type Shipment = {
  uuid: string;
  order_uuid: string;
  shipment_number: string;
  status: ShipmentStatus;
  recipient: ShipmentRecipient;
  carrier_code: string | null;
  carrier_name: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
  shipping_fee: string | null;
  cod_amount: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
  packed_at: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
};

export type ShipmentTrackingPayload = {
  carrier_code?: string | null;
  carrier_name?: string | null;
  tracking_number?: string | null;
  tracking_url?: string | null;
  shipping_fee?: number | string | null;
  cod_amount?: number | string | null;
  note?: string | null;
};

export type ShipmentListResponse = {
  items: Shipment[];
};

export type OrderCreatePayload = {
  customer_uuid: string;
  conversation_uuid?: string | null;
  items: OrderItemCreate[];
  currency?: string;
  discount_amount?: number;
  shipping_fee?: number;
  shipping_address?: string | null;
  shipping_destination?: ShippingDestinationInput | null;
  note?: string | null;
};

export type OrderUpdatePayload = {
  status?: OrderStatus;
  payment_status?: PaymentStatus;
  shipping_status?: ShippingStatus;
};

export type OrderListItem = {
  uuid: string;
  order_number: string;
  customer_uuid: string;
  customer_name: string | null;
  customer_name_snapshot: string | null;
  customer_phone_snapshot: string | null;
  customer_email_snapshot: string | null;
  conversation_uuid: string | null;
  status: OrderStatus;
  payment_status: PaymentStatus;
  shipping_status: ShippingStatus;
  currency: string;
  subtotal_amount: string;
  discount_amount: string;
  shipping_fee: string;
  total_amount: string;
  item_count: number;
  shipping_address: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
  cancelled_at: string | null;
};

export type OrderResponse = OrderListItem & {
  shipping_destination: ShippingDestination | null;
  items: OrderItem[];
  deleted_at: string | null;
};

export type OrderListResponse = {
  items: OrderListItem[];
  meta: PaginationMeta;
};

export type OrderListFilters = {
  page?: number;
  pageSize?: number;
  search?: string;
  queue?: OrderOperationalQueue;
  orderStatus?: OrderStatus;
  paymentStatus?: PaymentStatus;
  shippingStatus?: ShippingStatus;
};

export type OrderOperationalSummary = Record<OrderQueueSelection, number>;

export type OrderTimelineActor = {
  name: string | null;
  email: string | null;
};

export type OrderEventType =
  | "ORDER_CREATED"
  | "ORDER_CONFIRMED"
  | "ORDER_CANCELLED"
  | "PAYMENT_STATUS_CHANGED"
  | "SHIPPING_STATUS_CHANGED";

export type OrderEventTimelineItem = {
  kind: "order_event";
  public_id: string;
  event_type: OrderEventType;
  from_value: string | null;
  to_value: string | null;
  actor: OrderTimelineActor | null;
  created_at: string;
};

export type InventoryMovementTimelineItem = {
  kind: "inventory_movement";
  public_id: string;
  movement_type: "ORDER_OUT" | "ORDER_CANCEL_RESTORE";
  product_name: string;
  sku: string | null;
  quantity_delta: number;
  quantity_before: number;
  quantity_after: number;
  actor: OrderTimelineActor | null;
  created_at: string;
};

export type ShipmentEventTimelineItem = {
  kind: "shipment_event";
  public_id: string;
  shipment_uuid: string;
  shipment_number: string;
  event_type: "CREATED" | "PACKED" | "SHIPPED" | "DELIVERED" | "CANCELLED" | "TRACKING_UPDATED";
  from_value: string | null;
  to_value: string | null;
  details: Record<string, unknown> | null;
  actor: OrderTimelineActor | null;
  created_at: string;
};

export type OrderTimelineItem = OrderEventTimelineItem | InventoryMovementTimelineItem | ShipmentEventTimelineItem;

export type OrderTimelineResponse = {
  items: OrderTimelineItem[];
};

export type CustomerOrderSummary = {
  order_count: number;
  total_spend: string;
  latest_order_at: string | null;
};
