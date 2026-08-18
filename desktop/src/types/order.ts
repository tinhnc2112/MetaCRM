import type { PaginationMeta } from "./messenger";

export type OrderStatus = "draft" | "confirmed" | "cancelled";
export type PaymentStatus = "unpaid" | "partial" | "paid" | "refunded";
export type ShippingStatus = "pending" | "packed" | "shipped" | "delivered" | "cancelled";

export type OrderItem = {
  uuid: string;
  item_name: string;
  sku: string | null;
  quantity: number;
  unit_price: string;
  line_total: string;
  note: string | null;
  created_at: string;
  updated_at: string;
};

export type OrderItemCreate = {
  item_name: string;
  sku?: string | null;
  quantity: number;
  unit_price: number;
  note?: string | null;
};

export type OrderCreatePayload = {
  customer_uuid: string;
  conversation_uuid?: string | null;
  items: OrderItemCreate[];
  currency?: string;
  discount_amount?: number;
  shipping_fee?: number;
  shipping_address?: string | null;
  note?: string | null;
};

export type OrderListItem = {
  uuid: string;
  order_number: string;
  customer_uuid: string;
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
  items: OrderItem[];
  deleted_at: string | null;
};

export type OrderListResponse = {
  items: OrderListItem[];
  meta: PaginationMeta;
};

export type CustomerOrderSummary = {
  order_count: number;
  total_spend: string;
  latest_order_at: string | null;
};
