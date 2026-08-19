import { Alert, Button, Descriptions, Divider, Empty, List, Modal, Select, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { OrderActivityTimeline } from "./OrderActivityTimeline";
import type {
  OrderResponse,
  OrderStatus,
  OrderTimelineItem,
  OrderUpdatePayload,
  PaymentStatus,
  ShippingStatus
} from "../types/order";

const PAYMENT_OPTIONS: Array<{ label: string; value: PaymentStatus }> = [
  { label: "Unpaid", value: "unpaid" },
  { label: "Partial", value: "partial" },
  { label: "Paid", value: "paid" },
  { label: "Refunded", value: "refunded" }
];

const SHIPPING_OPTIONS: Array<{ label: string; value: ShippingStatus }> = [
  { label: "Pending", value: "pending" },
  { label: "Packed", value: "packed" },
  { label: "Shipped", value: "shipped" },
  { label: "Delivered", value: "delivered" },
  { label: "Cancelled", value: "cancelled" }
];

type OrderOperationsDetailProps = {
  open: boolean;
  order: OrderResponse | null;
  loading: boolean;
  loadError: string | null;
  operationError: string | null;
  activityItems: OrderTimelineItem[];
  activityLoading: boolean;
  activityError: string | null;
  updating: boolean;
  onClose: () => void;
  onRetry: () => void;
  onRetryActivity: () => void;
  onOpenCustomer: (customerUuid: string) => void;
  onUpdate: (payload: OrderUpdatePayload) => void;
  onLifecycleChange: (status: OrderStatus) => void;
};

export function OrderOperationsDetail({
  open,
  order,
  loading,
  loadError,
  operationError,
  activityItems,
  activityLoading,
  activityError,
  updating,
  onClose,
  onRetry,
  onRetryActivity,
  onOpenCustomer,
  onUpdate,
  onLifecycleChange
}: OrderOperationsDetailProps) {
  const [paymentStatus, setPaymentStatus] = useState<PaymentStatus>("unpaid");
  const [shippingStatus, setShippingStatus] = useState<ShippingStatus>("pending");

  useEffect(() => {
    if (!order) {
      return;
    }
    setPaymentStatus(order.payment_status);
    setShippingStatus(order.shipping_status);
  }, [order?.uuid, order?.payment_status, order?.shipping_status]);

  const statusChanged = Boolean(
    order &&
      (paymentStatus !== order.payment_status || shippingStatus !== order.shipping_status)
  );

  return (
    <Modal
      title={order ? `Order ${order.order_number}` : "Order details"}
      open={open}
      width={860}
      footer={<Button onClick={onClose}>Close</Button>}
      onCancel={onClose}
      destroyOnClose
      styles={{ body: { maxHeight: "75vh", overflowY: "auto" } }}
    >
      {loading ? (
        <div className="order-detail-loading"><Spin /></div>
      ) : loadError ? (
        <Alert
          type="error"
          showIcon
          message="Unable to load Order."
          description={loadError}
          action={<Button onClick={onRetry}>Retry</Button>}
        />
      ) : !order ? (
        <Empty description="Order details are unavailable" />
      ) : (
        <div className="order-operations-detail">
          {operationError ? <Alert type="error" showIcon message={operationError} /> : null}

          <div className="order-detail-heading">
            <Space wrap>
              <OrderStatusBadge value={order.status} />
              <PaymentStatusBadge value={order.payment_status} />
              <ShippingStatusBadge value={order.shipping_status} />
            </Space>
            <Button type="link" onClick={() => onOpenCustomer(order.customer_uuid)}>
              Open Customer
            </Button>
          </div>

          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="Customer">
              {order.customer_name ?? order.customer_name_snapshot ?? "Unknown customer"}
            </Descriptions.Item>
            <Descriptions.Item label="Created">{formatTimestamp(order.created_at)}</Descriptions.Item>
            <Descriptions.Item label="Subtotal">{formatMoney(order.subtotal_amount, order.currency)}</Descriptions.Item>
            <Descriptions.Item label="Discount">{formatMoney(order.discount_amount, order.currency)}</Descriptions.Item>
            <Descriptions.Item label="Shipping fee">{formatMoney(order.shipping_fee, order.currency)}</Descriptions.Item>
            <Descriptions.Item label="Total">
              <Typography.Text strong>{formatMoney(order.total_amount, order.currency)}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="Shipping address" span={2}>
              {order.shipping_address ?? "Not provided"}
            </Descriptions.Item>
            <Descriptions.Item label="Note" span={2}>{order.note ?? "No note"}</Descriptions.Item>
            <Descriptions.Item label="Updated">{formatTimestamp(order.updated_at)}</Descriptions.Item>
            <Descriptions.Item label="Cancelled">
              {order.cancelled_at ? formatTimestamp(order.cancelled_at) : "—"}
            </Descriptions.Item>
          </Descriptions>

          <section className="order-detail-operations">
            <div>
              <Typography.Title level={5}>Lifecycle</Typography.Title>
              <Typography.Text type="secondary">
                Order status controls inventory. Payment and shipping statuses are operational labels only.
              </Typography.Text>
            </div>
            <Space wrap>
              {order.status === "draft" ? (
                <Button type="primary" loading={updating} onClick={() => onLifecycleChange("confirmed")}>
                  Confirm Order
                </Button>
              ) : null}
              {order.status !== "cancelled" ? (
                <Button danger disabled={updating} onClick={() => onLifecycleChange("cancelled")}>
                  Cancel Order
                </Button>
              ) : null}
            </Space>
            <div className="order-detail-status-fields">
              <label>
                <span>Payment</span>
                <Select
                  aria-label="Payment status"
                  value={paymentStatus}
                  options={PAYMENT_OPTIONS}
                  onChange={setPaymentStatus}
                  disabled={updating}
                />
              </label>
              <label>
                <span>Shipping</span>
                <Select
                  aria-label="Shipping status"
                  value={shippingStatus}
                  options={SHIPPING_OPTIONS}
                  onChange={setShippingStatus}
                  disabled={updating}
                />
              </label>
              <Button
                type="primary"
                disabled={!statusChanged || updating}
                loading={updating}
                onClick={() => onUpdate({ payment_status: paymentStatus, shipping_status: shippingStatus })}
              >
                Save statuses
              </Button>
            </div>
          </section>

          <Divider />
          <Typography.Title level={5}>Items</Typography.Title>
          <List
            dataSource={order.items}
            locale={{ emptyText: "No items" }}
            renderItem={(item) => (
              <List.Item className="order-detail-item">
                <div className="order-detail-item-name">
                  <Typography.Text strong>{item.item_name}</Typography.Text>
                  <Typography.Text type="secondary">{item.sku ? `SKU ${item.sku}` : "Manual / no SKU"}</Typography.Text>
                  {item.note ? <Typography.Text type="secondary">{item.note}</Typography.Text> : null}
                </div>
                <Space size="large">
                  <Typography.Text>{item.quantity} × {formatMoney(item.unit_price, order.currency)}</Typography.Text>
                  <Typography.Text strong>{formatMoney(item.line_total, order.currency)}</Typography.Text>
                </Space>
              </List.Item>
            )}
          />

          <Divider />
          <Typography.Title level={5}>Activity</Typography.Title>
          <Typography.Paragraph type="secondary">
            Recorded Order actions and directly linked Inventory movements, shown chronologically.
          </Typography.Paragraph>
          <OrderActivityTimeline
            items={activityItems}
            loading={activityLoading}
            error={activityError}
            onRetry={onRetryActivity}
          />
        </div>
      )}
    </Modal>
  );
}

export function OrderStatusBadge({ value }: { value: OrderStatus }) {
  return <Tag color={value === "confirmed" ? "green" : value === "cancelled" ? "red" : "blue"}>Order · {labelize(value)}</Tag>;
}

export function PaymentStatusBadge({ value }: { value: PaymentStatus }) {
  const color = value === "paid" ? "green" : value === "refunded" ? "purple" : value === "partial" ? "gold" : "orange";
  return <Tag color={color}>Payment · {labelize(value)}</Tag>;
}

export function ShippingStatusBadge({ value }: { value: ShippingStatus }) {
  const color = value === "delivered" ? "green" : value === "cancelled" ? "red" : value === "shipped" ? "cyan" : value === "packed" ? "geekblue" : "default";
  return <Tag color={color}>Shipping · {labelize(value)}</Tag>;
}

function labelize(value: string): string {
  return value.slice(0, 1).toUpperCase() + value.slice(1).replace(/_/g, " ");
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatMoney(value: string, currency: string): string {
  const amount = Number(value);
  return `${Number.isFinite(amount) ? amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value} ${currency}`;
}
