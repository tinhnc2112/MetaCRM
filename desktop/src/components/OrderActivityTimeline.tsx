import { Alert, Button, Empty, Spin, Timeline, Typography } from "antd";

import type { OrderEventTimelineItem, OrderTimelineItem } from "../types/order";

type OrderActivityTimelineProps = {
  items: OrderTimelineItem[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
};

export function OrderActivityTimeline({
  items,
  loading,
  error,
  onRetry
}: OrderActivityTimelineProps) {
  if (loading) {
    return <div className="order-activity-loading"><Spin size="small" /></div>;
  }
  if (error) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Unable to load activity."
        description={error}
        action={<Button onClick={onRetry}>Retry</Button>}
      />
    );
  }
  if (items.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="No recorded activity is available before activity tracking was enabled."
      />
    );
  }

  return (
    <Timeline
      className="order-activity-timeline"
      items={items.map((item) => ({
        key: `${item.kind}:${item.public_id}`,
        color: timelineColor(item),
        children: (
          <div className="order-activity-entry">
            <Typography.Text strong>{activityTitle(item)}</Typography.Text>
            {item.kind === "inventory_movement" ? (
              <Typography.Text>
                {item.product_name}{item.sku ? ` · SKU ${item.sku}` : ""} · {signed(item.quantity_delta)}
                {` · ${item.quantity_before} → ${item.quantity_after}`}
              </Typography.Text>
            ) : null}
            {item.kind === "shipment_event" && item.event_type === "TRACKING_UPDATED" ? (
              <Typography.Text>{trackingDetails(item.details)}</Typography.Text>
            ) : null}
            <Typography.Text type="secondary">
              {formatTimestamp(item.created_at)} · {actorLabel(item.actor)}
            </Typography.Text>
          </div>
        )
      }))}
    />
  );
}

function activityTitle(item: OrderTimelineItem): string {
  if (item.kind === "inventory_movement") {
    return item.movement_type === "ORDER_OUT" ? "Inventory consumed" : "Inventory restored";
  }
  if (item.kind === "shipment_event") {
    const labels: Record<string, string> = {
      CREATED: "Shipment created",
      PACKED: "Shipment packed",
      SHIPPED: "Shipment shipped",
      DELIVERED: "Shipment delivered",
      CANCELLED: "Shipment cancelled",
      TRACKING_UPDATED: "Shipment tracking updated"
    };
    return `${labels[item.event_type] ?? "Shipment updated"} · ${item.shipment_number}`;
  }
  const fixedLabels: Partial<Record<OrderEventTimelineItem["event_type"], string>> = {
    ORDER_CREATED: "Order created",
    ORDER_CONFIRMED: "Order confirmed",
    ORDER_CANCELLED: "Order cancelled"
  };
  if (fixedLabels[item.event_type]) {
    return fixedLabels[item.event_type] as string;
  }
  const dimension = item.event_type === "PAYMENT_STATUS_CHANGED" ? "Payment" : "Shipping";
  return `${dimension}: ${labelize(item.from_value)} → ${labelize(item.to_value)}`;
}

function timelineColor(item: OrderTimelineItem): string {
  if (item.kind === "inventory_movement") {
    return item.movement_type === "ORDER_OUT" ? "blue" : "green";
  }
  if (item.kind === "shipment_event") {
    return item.event_type === "CANCELLED" ? "red" : item.event_type === "DELIVERED" ? "green" : "blue";
  }
  if (item.event_type === "ORDER_CANCELLED") {
    return "red";
  }
  if (item.event_type === "ORDER_CONFIRMED") {
    return "green";
  }
  return "blue";
}

function trackingDetails(details: Record<string, unknown> | null): string {
  const carrier = typeof details?.carrier === "string" ? details.carrier : null;
  const trackingNumber = typeof details?.tracking_number === "string"
    ? details.tracking_number
    : null;
  return [carrier, trackingNumber].filter(Boolean).join(" Â· ") || "Manual tracking metadata changed";
}

function actorLabel(actor: OrderTimelineItem["actor"]): string {
  if (actor?.name && actor.email) {
    return `${actor.name} (${actor.email})`;
  }
  return actor?.name || actor?.email || "System";
}

function labelize(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return value.slice(0, 1).toUpperCase() + value.slice(1).replace(/_/g, " ");
}

function signed(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
