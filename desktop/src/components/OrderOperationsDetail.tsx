import { Alert, Button, Descriptions, Divider, Empty, Input, InputNumber, List, Modal, Select, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { OrderActivityTimeline } from "./OrderActivityTimeline";
import type {
  OrderResponse,
  OrderStatus,
  OrderTimelineItem,
  OrderUpdatePayload,
  PaymentStatus,
  Shipment,
  ShipmentStatus,
  ShipmentTrackingPayload,
  ShippingDestinationInput,
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
  shipments: Shipment[];
  shipmentsLoading: boolean;
  shipmentsError: string | null;
  activityItems: OrderTimelineItem[];
  activityLoading: boolean;
  activityError: string | null;
  updating: boolean;
  onClose: () => void;
  onRetry: () => void;
  onRetryActivity: () => void;
  onOpenCustomer: (customerUuid: string) => void;
  onUpdate: (payload: OrderUpdatePayload) => void;
  onUpdateShipping: (payload: ShippingDestinationInput) => void;
  onLifecycleChange: (status: OrderStatus) => void;
  onCreateShipment: () => void;
  onShipmentStatusChange: (shipmentUuid: string, status: ShipmentStatus) => void;
  onShipmentTrackingUpdate: (shipmentUuid: string, payload: ShipmentTrackingPayload) => void;
};

export function OrderOperationsDetail({
  open,
  order,
  loading,
  loadError,
  operationError,
  shipments,
  shipmentsLoading,
  shipmentsError,
  activityItems,
  activityLoading,
  activityError,
  updating,
  onClose,
  onRetry,
  onRetryActivity,
  onOpenCustomer,
  onUpdate,
  onUpdateShipping,
  onLifecycleChange,
  onCreateShipment,
  onShipmentStatusChange,
  onShipmentTrackingUpdate
}: OrderOperationsDetailProps) {
  const [paymentStatus, setPaymentStatus] = useState<PaymentStatus>("unpaid");
  const [shippingStatus, setShippingStatus] = useState<ShippingStatus>("pending");
  const [shippingEditorOpen, setShippingEditorOpen] = useState(false);
  const [shippingDraft, setShippingDraft] = useState(() => emptyShippingDraft());
  const [trackingEditorShipment, setTrackingEditorShipment] = useState<Shipment | null>(null);
  const [trackingDraft, setTrackingDraft] = useState(() => emptyTrackingDraft());

  useEffect(() => {
    if (!order) {
      return;
    }
    setPaymentStatus(order.payment_status);
    setShippingStatus(order.shipping_status);
    setShippingDraft(buildShippingDraft(order));
    setShippingEditorOpen(false);
    setTrackingEditorShipment(null);
  }, [order?.uuid, order?.payment_status, order?.shipping_status, order?.updated_at]);

  useEffect(() => {
    if (!trackingEditorShipment) {
      return;
    }
    const refreshed = shipments.find((shipment) => shipment.uuid === trackingEditorShipment.uuid);
    if (refreshed) {
      setTrackingEditorShipment(refreshed);
      setTrackingDraft(buildTrackingDraft(refreshed));
    }
  }, [shipments, trackingEditorShipment?.uuid]);

  const statusChanged = Boolean(
    order &&
      (paymentStatus !== order.payment_status || shippingStatus !== order.shipping_status)
  );
  const hasShipments = shipments.length > 0;
  const hasActiveShipments = shipments.some((shipment) => shipment.status !== "cancelled");
  const shippingEditable = Boolean(
    order &&
      order.status !== "cancelled" &&
      !hasActiveShipments &&
      (hasShipments || !["shipped", "delivered", "cancelled"].includes(order.shipping_status))
  );
  const canCreateShipment = Boolean(
    order?.status === "confirmed" && order.shipping_destination?.is_complete
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
            <Descriptions.Item label="Note" span={2}>{order.note ?? "No note"}</Descriptions.Item>
            <Descriptions.Item label="Updated">{formatTimestamp(order.updated_at)}</Descriptions.Item>
            <Descriptions.Item label="Cancelled">
              {order.cancelled_at ? formatTimestamp(order.cancelled_at) : "—"}
            </Descriptions.Item>
          </Descriptions>

          <Divider />
          <section aria-label="Shipping and delivery information">
            <div className="order-detail-heading">
              <div>
                <Typography.Title level={5}>Shipping / delivery</Typography.Title>
                <Tag color={order.shipping_destination?.is_complete ? "green" : "gold"}>
                  {order.shipping_destination?.is_complete ? "Ready" : "Shipping information incomplete"}
                </Tag>
              </div>
              <Button
                disabled={!shippingEditable || updating}
                onClick={() => setShippingEditorOpen(true)}
              >
                Edit shipping information
              </Button>
            </div>
            {!shippingEditable ? (
              <Alert
                type="info"
                showIcon
                message="Shipping information is locked after dispatch or cancellation."
              />
            ) : null}
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Recipient">
                {order.shipping_destination?.recipient_name ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="Phone">
                {order.shipping_destination?.recipient_phone ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="Address" span={2}>
                {order.shipping_destination?.address_line ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="Ward">
                {order.shipping_destination?.ward ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="District">
                {order.shipping_destination?.district ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="Province">
                {order.shipping_destination?.province ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="Postal code">
                {order.shipping_destination?.postal_code ?? "Not provided"}
              </Descriptions.Item>
              <Descriptions.Item label="Country">
                {order.shipping_destination?.country_code ?? "VN"}
              </Descriptions.Item>
              <Descriptions.Item label="Delivery note">
                {order.shipping_destination?.note ?? "Not provided"}
              </Descriptions.Item>
            </Descriptions>
          </section>

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
                disabled={updating || hasShipments}
              />
            </label>
              <Button
                type="primary"
                disabled={!statusChanged || updating}
                loading={updating}
                onClick={() => onUpdate(hasShipments ? { payment_status: paymentStatus } : { payment_status: paymentStatus, shipping_status: shippingStatus })}
              >
                Save statuses
              </Button>
            </div>
          </section>

          <Divider />
          <section aria-label="Shipments">
            <div className="order-detail-heading">
              <div>
                <Typography.Title level={5}>Shipments</Typography.Title>
                <Typography.Text type="secondary">
                  Fulfillment status is derived from Shipments after the first Shipment is created.
                </Typography.Text>
              </div>
              <Button
                type="primary"
                disabled={!canCreateShipment || updating}
                loading={updating}
                onClick={onCreateShipment}
              >
                Create Shipment
              </Button>
            </div>
            {!canCreateShipment ? (
              <Alert
                type="info"
                showIcon
                message={
                  order.status !== "confirmed"
                    ? "Order must be confirmed first."
                    : "Shipping information incomplete."
                }
              />
            ) : null}
            {shipmentsError ? (
              <Alert type="warning" showIcon message="Unable to load Shipments." description={shipmentsError} />
            ) : shipmentsLoading ? (
              <div className="order-detail-loading"><Spin size="small" /></div>
            ) : shipments.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No Shipments" />
            ) : (
              <List
                dataSource={shipments}
                rowKey="uuid"
                renderItem={(shipment) => (
                  <List.Item
                    actions={[
                      ...(shipmentTrackingEditable(shipment) ? [
                        <Button
                          key="tracking"
                          size="small"
                          disabled={updating}
                          onClick={() => {
                            setTrackingEditorShipment(shipment);
                            setTrackingDraft(buildTrackingDraft(shipment));
                          }}
                        >
                          Edit tracking
                        </Button>
                      ] : []),
                      ...shipmentActions(shipment).map((action) => (
                        <Button
                          key={action.status}
                          size="small"
                          danger={action.status === "cancelled"}
                          disabled={updating}
                          onClick={() => onShipmentStatusChange(shipment.uuid, action.status)}
                        >
                          {action.label}
                        </Button>
                      ))
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        <Space wrap>
                          <Typography.Text strong>{shipment.shipment_number}</Typography.Text>
                          <ShipmentStatusBadge value={shipment.status} />
                          {shipment.carrier_name || shipment.carrier_code ? (
                            <Tag>{shipment.carrier_name ?? shipment.carrier_code}</Tag>
                          ) : null}
                          {shipment.tracking_number ? <Tag>{shipment.tracking_number}</Tag> : null}
                        </Space>
                      }
                      description={
                        <Space direction="vertical" size={2}>
                          <Typography.Text>
                            {shipment.recipient.recipient_name} · {shipment.recipient.recipient_phone}
                          </Typography.Text>
                          <Typography.Text type="secondary">
                            {destinationSummary(shipment.recipient)}
                          </Typography.Text>
                          <Typography.Text type="secondary">
                            Created {formatTimestamp(shipment.created_at)}
                          </Typography.Text>
                          <ShipmentTrackingSummary shipment={shipment} />
                        </Space>
                      }
                    />
                  </List.Item>
                )}
              />
            )}
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

          <Modal
            title="Edit shipping information"
            open={shippingEditorOpen}
            onCancel={() => setShippingEditorOpen(false)}
            onOk={() => {
              onUpdateShipping(shippingDraftPayload(shippingDraft));
              setShippingEditorOpen(false);
            }}
            okText="Save shipping information"
            confirmLoading={updating}
            destroyOnClose
          >
            <div className="create-order-form">
              <Input aria-label="Recipient name" placeholder="Recipient name" value={shippingDraft.recipient_name} maxLength={255} onChange={(event) => setShippingDraft({ ...shippingDraft, recipient_name: event.target.value })} />
              <Input aria-label="Phone" placeholder="Phone" value={shippingDraft.recipient_phone} maxLength={32} onChange={(event) => setShippingDraft({ ...shippingDraft, recipient_phone: event.target.value })} />
              <Input.TextArea aria-label="Address" placeholder="Address" value={shippingDraft.address_line} maxLength={5000} onChange={(event) => setShippingDraft({ ...shippingDraft, address_line: event.target.value })} />
              <Input aria-label="Ward" placeholder="Ward" value={shippingDraft.ward} maxLength={255} onChange={(event) => setShippingDraft({ ...shippingDraft, ward: event.target.value })} />
              <Input aria-label="District" placeholder="District" value={shippingDraft.district} maxLength={255} onChange={(event) => setShippingDraft({ ...shippingDraft, district: event.target.value })} />
              <Input aria-label="Province" placeholder="Province" value={shippingDraft.province} maxLength={255} onChange={(event) => setShippingDraft({ ...shippingDraft, province: event.target.value })} />
              <Input aria-label="Postal code" placeholder="Postal code" value={shippingDraft.postal_code} maxLength={32} onChange={(event) => setShippingDraft({ ...shippingDraft, postal_code: event.target.value })} />
              <Input aria-label="Country" placeholder="Country" value={shippingDraft.country_code} maxLength={2} onChange={(event) => setShippingDraft({ ...shippingDraft, country_code: event.target.value.toUpperCase() })} />
              <Input.TextArea aria-label="Delivery note" placeholder="Delivery note" value={shippingDraft.note} maxLength={5000} onChange={(event) => setShippingDraft({ ...shippingDraft, note: event.target.value })} />
            </div>
          </Modal>
          <Modal
            title="Edit tracking"
            open={Boolean(trackingEditorShipment)}
            onCancel={() => setTrackingEditorShipment(null)}
            onOk={() => {
              if (!trackingEditorShipment) {
                return;
              }
              onShipmentTrackingUpdate(
                trackingEditorShipment.uuid,
                trackingDraftPayload(trackingDraft)
              );
              setTrackingEditorShipment(null);
            }}
            okText="Save tracking"
            confirmLoading={updating}
            destroyOnClose
          >
            <div className="create-order-form">
              <Input aria-label="Carrier code" placeholder="Carrier code" value={trackingDraft.carrier_code} maxLength={64} onChange={(event) => setTrackingDraft({ ...trackingDraft, carrier_code: event.target.value })} />
              <Input aria-label="Carrier name" placeholder="Carrier name" value={trackingDraft.carrier_name} maxLength={255} onChange={(event) => setTrackingDraft({ ...trackingDraft, carrier_name: event.target.value })} />
              <Input aria-label="Tracking number" placeholder="Tracking number" value={trackingDraft.tracking_number} maxLength={255} onChange={(event) => setTrackingDraft({ ...trackingDraft, tracking_number: event.target.value })} />
              <Input aria-label="Tracking URL" placeholder="https://carrier.example/track/123" value={trackingDraft.tracking_url} maxLength={5000} onChange={(event) => setTrackingDraft({ ...trackingDraft, tracking_url: event.target.value })} />
              <InputNumber aria-label="Shipping fee" placeholder="Shipping fee" value={trackingDraft.shipping_fee} min="0" precision={2} stringMode onChange={(value) => setTrackingDraft({ ...trackingDraft, shipping_fee: value === null ? null : String(value) })} />
              <InputNumber aria-label="COD amount" placeholder="COD amount" value={trackingDraft.cod_amount} min="0" precision={2} stringMode onChange={(value) => setTrackingDraft({ ...trackingDraft, cod_amount: value === null ? null : String(value) })} />
              <Input.TextArea aria-label="Tracking note" placeholder="Note" value={trackingDraft.note} maxLength={5000} onChange={(event) => setTrackingDraft({ ...trackingDraft, note: event.target.value })} />
            </div>
          </Modal>
        </div>
      )}
    </Modal>
  );
}

type ShippingDraft = Record<
  "recipient_name" | "recipient_phone" | "address_line" | "ward" | "district" | "province" | "postal_code" | "country_code" | "note",
  string
>;

type TrackingDraft = {
  carrier_code: string;
  carrier_name: string;
  tracking_number: string;
  tracking_url: string;
  shipping_fee: string | null;
  cod_amount: string | null;
  note: string;
};

function emptyShippingDraft(): ShippingDraft {
  return {
    recipient_name: "",
    recipient_phone: "",
    address_line: "",
    ward: "",
    district: "",
    province: "",
    postal_code: "",
    country_code: "VN",
    note: ""
  };
}

function buildShippingDraft(order: OrderResponse): ShippingDraft {
  const destination = order.shipping_destination;
  return {
    recipient_name: destination?.recipient_name ?? order.customer_name_snapshot ?? "",
    recipient_phone: destination?.recipient_phone ?? order.customer_phone_snapshot ?? "",
    address_line: destination?.address_line ?? order.shipping_address ?? "",
    ward: destination?.ward ?? "",
    district: destination?.district ?? "",
    province: destination?.province ?? "",
    postal_code: destination?.postal_code ?? "",
    country_code: destination?.country_code ?? "VN",
    note: destination?.note ?? ""
  };
}

function shippingDraftPayload(draft: ShippingDraft): ShippingDestinationInput {
  const optional = (value: string) => value.trim() || null;
  return {
    recipient_name: optional(draft.recipient_name),
    recipient_phone: optional(draft.recipient_phone),
    address_line: optional(draft.address_line),
    ward: optional(draft.ward),
    district: optional(draft.district),
    province: optional(draft.province),
    postal_code: optional(draft.postal_code),
    country_code: optional(draft.country_code)?.toUpperCase() ?? null,
    note: optional(draft.note)
  };
}

function emptyTrackingDraft(): TrackingDraft {
  return {
    carrier_code: "",
    carrier_name: "",
    tracking_number: "",
    tracking_url: "",
    shipping_fee: null,
    cod_amount: null,
    note: ""
  };
}

function buildTrackingDraft(shipment: Shipment): TrackingDraft {
  return {
    carrier_code: shipment.carrier_code ?? "",
    carrier_name: shipment.carrier_name ?? "",
    tracking_number: shipment.tracking_number ?? "",
    tracking_url: shipment.tracking_url ?? "",
    shipping_fee: shipment.shipping_fee,
    cod_amount: shipment.cod_amount,
    note: shipment.note ?? ""
  };
}

function trackingDraftPayload(draft: TrackingDraft): ShipmentTrackingPayload {
  const optional = (value: string) => value.trim() || null;
  return {
    carrier_code: optional(draft.carrier_code),
    carrier_name: optional(draft.carrier_name),
    tracking_number: optional(draft.tracking_number),
    tracking_url: optional(draft.tracking_url),
    shipping_fee: draft.shipping_fee === null || draft.shipping_fee === "" ? null : draft.shipping_fee,
    cod_amount: draft.cod_amount === null || draft.cod_amount === "" ? null : draft.cod_amount,
    note: optional(draft.note)
  };
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

function ShipmentStatusBadge({ value }: { value: ShipmentStatus }) {
  const color = value === "delivered" ? "green" : value === "cancelled" ? "red" : value === "shipped" ? "cyan" : value === "packed" ? "geekblue" : "default";
  return <Tag color={color}>Shipment · {labelize(value)}</Tag>;
}

function shipmentActions(shipment: Shipment): Array<{ status: ShipmentStatus; label: string }> {
  if (shipment.status === "ready") {
    return [
      { status: "packed", label: "Mark packed" },
      { status: "cancelled", label: "Cancel" }
    ];
  }
  if (shipment.status === "packed") {
    return [
      { status: "shipped", label: "Mark shipped" },
      { status: "cancelled", label: "Cancel" }
    ];
  }
  if (shipment.status === "shipped") {
    return [{ status: "delivered", label: "Mark delivered" }];
  }
  return [];
}

function shipmentTrackingEditable(shipment: Shipment): boolean {
  return ["ready", "packed", "shipped"].includes(shipment.status);
}

function ShipmentTrackingSummary({ shipment }: { shipment: Shipment }) {
  const rows: Array<{ label: string; value: ReactNode }> = [];
  if (shipment.carrier_code) {
    rows.push({ label: "Carrier code", value: shipment.carrier_code });
  }
  if (shipment.carrier_name) {
    rows.push({ label: "Carrier", value: shipment.carrier_name });
  }
  if (shipment.tracking_number) {
    rows.push({ label: "Tracking number", value: shipment.tracking_number });
  }
  if (shipment.tracking_url) {
    rows.push({
      label: "Tracking URL",
      value: (
        <Typography.Link href={shipment.tracking_url} target="_blank" rel="noopener noreferrer">
          {shipment.tracking_url}
        </Typography.Link>
      )
    });
  }
  if (shipment.shipping_fee) {
    rows.push({ label: "Shipping fee", value: shipment.shipping_fee });
  }
  if (shipment.cod_amount) {
    rows.push({ label: "COD amount", value: shipment.cod_amount });
  }
  if (shipment.note) {
    rows.push({ label: "Note", value: shipment.note });
  }
  if (rows.length === 0) {
    return null;
  }
  return (
    <Descriptions size="small" column={1} className="shipment-tracking-summary">
      {rows.map((row) => (
        <Descriptions.Item key={row.label} label={row.label}>
          {row.value}
        </Descriptions.Item>
      ))}
    </Descriptions>
  );
}

function destinationSummary(recipient: Shipment["recipient"]): string {
  return [
    recipient.address_line,
    recipient.ward,
    recipient.district,
    recipient.province,
    recipient.postal_code,
    recipient.country_code
  ].filter(Boolean).join(", ");
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
