import { EyeOutlined, SearchOutlined, ShoppingCartOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Empty, Input, Pagination, Select, Space, Spin, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  OrderOperationsDetail,
  OrderStatusBadge,
  PaymentStatusBadge,
  ShippingStatusBadge
} from "../components/OrderOperationsDetail";
import { getCurrentFacebookPage } from "../services/facebookService";
import {
  createOrderShipment,
  getOrder,
  getOrderOperationalSummary,
  getOrderTimeline,
  listOrderShipments,
  listOrders,
  updateOrder,
  updateOrderShippingDestination,
  updateShipmentStatus,
  updateShipmentTracking
} from "../services/orderService";
import type {
  OrderListItem,
  OrderOperationalSummary,
  OrderQueueSelection,
  OrderStatus,
  OrderUpdatePayload,
  PaymentStatus,
  ShipmentStatus,
  ShipmentTrackingPayload,
  ShippingDestinationInput,
  ShippingStatus
} from "../types/order";

const PAGE_SIZE = 20;
type OrderFilter = "all" | OrderStatus;
type PaymentFilter = "all" | PaymentStatus;
type ShippingFilter = "all" | ShippingStatus;

type UpdateVariables = {
  pageId: string;
  orderUuid: string;
  customerUuid: string;
  payload: OrderUpdatePayload;
  contextKey: string;
};

type ShippingUpdateVariables = Omit<UpdateVariables, "payload"> & {
  payload: ShippingDestinationInput;
};

type ShipmentCreateVariables = Omit<UpdateVariables, "payload">;

type ShipmentStatusVariables = Omit<UpdateVariables, "payload"> & {
  shipmentUuid: string;
  status: ShipmentStatus;
};

type ShipmentTrackingVariables = Omit<UpdateVariables, "payload"> & {
  shipmentUuid: string;
  payload: ShipmentTrackingPayload;
};

export function OrderOperationsPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [orderStatus, setOrderStatus] = useState<OrderFilter>("all");
  const [paymentStatus, setPaymentStatus] = useState<PaymentFilter>("all");
  const [shippingStatus, setShippingStatus] = useState<ShippingFilter>("all");
  const [queue, setQueue] = useState<OrderQueueSelection>("all");
  const [page, setPage] = useState(1);
  const [selectedOrderUuid, setSelectedOrderUuid] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);

  const currentPageQuery = useQuery({
    queryKey: ["facebook-current-page"],
    queryFn: getCurrentFacebookPage
  });
  const currentPageId = currentPageQuery.data?.item?.page_id ?? null;
  const currentPageName = currentPageQuery.data?.item?.name ?? null;
  const currentContextKey = JSON.stringify([currentPageId, selectedOrderUuid]);
  const currentContextRef = useRef(currentContextKey);
  currentContextRef.current = currentContextKey;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(searchText.trim());
      setPage(1);
    }, 400);
    return () => window.clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    setPage(1);
    setQueue("all");
    setSelectedOrderUuid(null);
    setOperationError(null);
  }, [currentPageId]);

  const filters = {
    page,
    pageSize: PAGE_SIZE,
    search: search || undefined,
    queue: queue === "all" ? undefined : queue,
    orderStatus: orderStatus === "all" ? undefined : orderStatus,
    paymentStatus: paymentStatus === "all" ? undefined : paymentStatus,
    shippingStatus: shippingStatus === "all" ? undefined : shippingStatus
  };
  const ordersQuery = useQuery({
    queryKey: ["orders", currentPageId, filters],
    queryFn: () => listOrders(filters),
    enabled: Boolean(currentPageId)
  });
  const operationalSummaryQuery = useQuery({
    queryKey: ["order-operational-summary", currentPageId],
    queryFn: getOrderOperationalSummary,
    enabled: Boolean(currentPageId)
  });
  const detailQuery = useQuery({
    queryKey: ["order", currentPageId, selectedOrderUuid],
    queryFn: () => getOrder(selectedOrderUuid as string),
    enabled: Boolean(currentPageId && selectedOrderUuid)
  });
  const timelineQuery = useQuery({
    queryKey: ["order-timeline", currentPageId, selectedOrderUuid],
    queryFn: () => getOrderTimeline(selectedOrderUuid as string),
    enabled: Boolean(currentPageId && selectedOrderUuid)
  });
  const shipmentsQuery = useQuery({
    queryKey: ["order-shipments", currentPageId, selectedOrderUuid],
    queryFn: () => listOrderShipments(selectedOrderUuid as string),
    enabled: Boolean(currentPageId && selectedOrderUuid)
  });

  const updateMutation = useMutation({
    mutationFn: ({ orderUuid, payload }: UpdateVariables) => updateOrder(orderUuid, payload),
    onSuccess: async (_, variables) => {
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: ["orders", variables.pageId] }),
        queryClient.invalidateQueries({
          queryKey: ["order-operational-summary", variables.pageId]
        }),
        queryClient.invalidateQueries({ queryKey: ["order", variables.pageId, variables.orderUuid] }),
        queryClient.invalidateQueries({
          queryKey: ["order-timeline", variables.pageId, variables.orderUuid]
        }),
        queryClient.invalidateQueries({ queryKey: ["customer-orders", variables.pageId, variables.customerUuid] }),
        queryClient.invalidateQueries({ queryKey: ["customer-order-summary", variables.pageId, variables.customerUuid] })
      ];
      if (variables.payload.status) {
        invalidations.push(
          queryClient.invalidateQueries({ queryKey: ["product-picker", variables.pageId] }),
          queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] })
        );
      }
      await Promise.all(invalidations);
      if (currentContextRef.current !== variables.contextKey) {
        return;
      }
      setOperationError(null);
      void message.success("Order updated.");
    },
    onError: async (error, variables) => {
      if (getHttpStatus(error) === 409) {
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["orders", variables.pageId] }),
          queryClient.invalidateQueries({
            queryKey: ["order-operational-summary", variables.pageId]
          }),
          queryClient.invalidateQueries({ queryKey: ["order", variables.pageId, variables.orderUuid] }),
          queryClient.invalidateQueries({
            queryKey: ["order-timeline", variables.pageId, variables.orderUuid]
          }),
          queryClient.invalidateQueries({ queryKey: ["product-picker", variables.pageId] }),
          queryClient.invalidateQueries({ queryKey: ["products", variables.pageId] })
        ]);
      }
      if (currentContextRef.current === variables.contextKey) {
        setOperationError(getReadableOrderError(error));
      }
    }
  });

  const shippingMutation = useMutation({
    mutationFn: ({ orderUuid, payload }: ShippingUpdateVariables) =>
      updateOrderShippingDestination(orderUuid, payload),
    onSuccess: async (_, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["orders", variables.pageId] }),
        queryClient.invalidateQueries({
          queryKey: ["order", variables.pageId, variables.orderUuid]
        }),
        queryClient.invalidateQueries({
          queryKey: ["customer-orders", variables.pageId, variables.customerUuid]
        })
      ]);
      if (currentContextRef.current !== variables.contextKey) {
        return;
      }
      setOperationError(null);
      void message.success("Shipping information updated.");
    },
    onError: (error, variables) => {
      if (currentContextRef.current === variables.contextKey) {
        setOperationError(getReadableOrderError(error));
      }
    }
  });

  const invalidateOrderWork = async (variables: { pageId: string; orderUuid: string; customerUuid: string }) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["orders", variables.pageId] }),
      queryClient.invalidateQueries({
        queryKey: ["order-operational-summary", variables.pageId]
      }),
      queryClient.invalidateQueries({ queryKey: ["order", variables.pageId, variables.orderUuid] }),
      queryClient.invalidateQueries({
        queryKey: ["order-timeline", variables.pageId, variables.orderUuid]
      }),
      queryClient.invalidateQueries({
        queryKey: ["order-shipments", variables.pageId, variables.orderUuid]
      }),
      queryClient.invalidateQueries({
        queryKey: ["customer-orders", variables.pageId, variables.customerUuid]
      }),
      queryClient.invalidateQueries({
        queryKey: ["customer-order-summary", variables.pageId, variables.customerUuid]
      })
    ]);
  };

  const createShipmentMutation = useMutation({
    mutationFn: ({ orderUuid }: ShipmentCreateVariables) => createOrderShipment(orderUuid),
    onSuccess: async (_, variables) => {
      await invalidateOrderWork(variables);
      if (currentContextRef.current !== variables.contextKey) {
        return;
      }
      setOperationError(null);
      void message.success("Shipment created.");
    },
    onError: (error, variables) => {
      if (currentContextRef.current === variables.contextKey) {
        setOperationError(getReadableOrderError(error));
      }
    }
  });

  const shipmentStatusMutation = useMutation({
    mutationFn: ({ shipmentUuid, status }: ShipmentStatusVariables) =>
      updateShipmentStatus(shipmentUuid, status),
    onSuccess: async (_, variables) => {
      await invalidateOrderWork(variables);
      if (currentContextRef.current !== variables.contextKey) {
        return;
      }
      setOperationError(null);
      void message.success("Shipment updated.");
    },
    onError: (error, variables) => {
      if (currentContextRef.current === variables.contextKey) {
        setOperationError(getReadableOrderError(error));
      }
    }
  });

  const shipmentTrackingMutation = useMutation({
    mutationFn: ({ shipmentUuid, payload }: ShipmentTrackingVariables) =>
      updateShipmentTracking(shipmentUuid, payload),
    onSuccess: async (_, variables) => {
      await invalidateOrderWork(variables);
      if (currentContextRef.current !== variables.contextKey) {
        return;
      }
      setOperationError(null);
      void message.success("Shipment tracking updated.");
    },
    onError: (error, variables) => {
      if (currentContextRef.current === variables.contextKey) {
        setOperationError(getReadableOrderError(error));
      }
    }
  });

  const submitUpdate = (payload: OrderUpdatePayload) => {
    const order = detailQuery.data;
    if (!currentPageId || !selectedOrderUuid || !order || updateMutation.isPending) {
      return;
    }
    setOperationError(null);
    updateMutation.mutate({
      pageId: currentPageId,
      orderUuid: selectedOrderUuid,
      customerUuid: order.customer_uuid,
      payload,
      contextKey: currentContextKey
    });
  };

  const submitShippingUpdate = (payload: ShippingDestinationInput) => {
    const order = detailQuery.data;
    if (!currentPageId || !selectedOrderUuid || !order || shippingMutation.isPending) {
      return;
    }
    setOperationError(null);
    shippingMutation.mutate({
      pageId: currentPageId,
      orderUuid: selectedOrderUuid,
      customerUuid: order.customer_uuid,
      payload,
      contextKey: currentContextKey
    });
  };

  const requestLifecycleChange = (status: OrderStatus) => {
    const order = detailQuery.data;
    if (!order) {
      return;
    }
    modal.confirm({
      title: status === "confirmed" ? "Confirm this Order?" : "Cancel this Order?",
      content:
        status === "confirmed"
          ? "Confirmation consumes tracked Product inventory."
          : order.status === "confirmed"
            ? "Cancelling this Order restores its tracked inventory."
            : "Cancelling this draft does not affect inventory.",
      okText: status === "confirmed" ? "Confirm Order" : "Cancel Order",
      okButtonProps: { danger: status === "cancelled" },
      onOk: () => submitUpdate({ status })
    });
  };

  const submitCreateShipment = () => {
    const order = detailQuery.data;
    if (!currentPageId || !selectedOrderUuid || !order || createShipmentMutation.isPending) {
      return;
    }
    setOperationError(null);
    createShipmentMutation.mutate({
      pageId: currentPageId,
      orderUuid: selectedOrderUuid,
      customerUuid: order.customer_uuid,
      contextKey: currentContextKey
    });
  };

  const submitShipmentStatus = (shipmentUuid: string, status: ShipmentStatus) => {
    const order = detailQuery.data;
    if (!currentPageId || !selectedOrderUuid || !order || shipmentStatusMutation.isPending) {
      return;
    }
    setOperationError(null);
    shipmentStatusMutation.mutate({
      pageId: currentPageId,
      orderUuid: selectedOrderUuid,
      customerUuid: order.customer_uuid,
      shipmentUuid,
      status,
      contextKey: currentContextKey
    });
  };

  const submitShipmentTracking = (shipmentUuid: string, payload: ShipmentTrackingPayload) => {
    const order = detailQuery.data;
    if (!currentPageId || !selectedOrderUuid || !order || shipmentTrackingMutation.isPending) {
      return;
    }
    setOperationError(null);
    shipmentTrackingMutation.mutate({
      pageId: currentPageId,
      orderUuid: selectedOrderUuid,
      customerUuid: order.customer_uuid,
      shipmentUuid,
      payload,
      contextKey: currentContextKey
    });
  };

  const orders = ordersQuery.data?.items ?? [];
  const pagination = ordersQuery.data?.meta ?? null;
  const operationalSummary: OrderOperationalSummary | null =
    operationalSummaryQuery.data ?? null;
  const hasActiveFilters = Boolean(
    search ||
      searchText ||
      queue !== "all" ||
      orderStatus !== "all" ||
      paymentStatus !== "all" ||
      shippingStatus !== "all"
  );
  const columns: TableColumnsType<OrderListItem> = [
    {
      title: "Order",
      dataIndex: "order_number",
      width: 210,
      render: (value: string, order) => (
        <Button type="link" className="order-number-link" onClick={() => openOrder(order.uuid)}>{value}</Button>
      )
    },
    {
      title: "Customer",
      width: 210,
      render: (_, order) => (
        <div className="order-customer-cell">
          <Button type="link" onClick={() => navigate(`/customers/${encodeURIComponent(order.customer_uuid)}`)}>
            {order.customer_name ?? order.customer_name_snapshot ?? "Unknown customer"}
          </Button>
          {order.customer_phone_snapshot ? <Typography.Text type="secondary">{order.customer_phone_snapshot}</Typography.Text> : null}
        </div>
      )
    },
    { title: "Order status", dataIndex: "status", width: 140, render: (value: OrderStatus) => <OrderStatusBadge value={value} /> },
    { title: "Payment", dataIndex: "payment_status", width: 145, render: (value: PaymentStatus) => <PaymentStatusBadge value={value} /> },
    { title: "Shipping", dataIndex: "shipping_status", width: 150, render: (value: ShippingStatus) => <ShippingStatusBadge value={value} /> },
    { title: "Items", dataIndex: "item_count", width: 80, align: "center" },
    { title: "Total", width: 145, align: "right", render: (_, order) => <Typography.Text strong>{formatMoney(order.total_amount, order.currency)}</Typography.Text> },
    { title: "Created", dataIndex: "created_at", width: 170, render: (value: string) => formatTimestamp(value) },
    { title: "Actions", width: 95, fixed: "right", render: (_, order) => <Button icon={<EyeOutlined />} onClick={() => openOrder(order.uuid)}>View</Button> }
  ];

  function openOrder(orderUuid: string) {
    setOperationError(null);
    setSelectedOrderUuid(orderUuid);
  }

  function clearFilters() {
    setSearchText("");
    setSearch("");
    setQueue("all");
    setOrderStatus("all");
    setPaymentStatus("all");
    setShippingStatus("all");
    setPage(1);
  }

  if (currentPageQuery.isLoading) {
    return <div className="order-page-loading"><Spin /></div>;
  }
  if (currentPageQuery.isError) {
    return <Alert type="error" showIcon message="Could not load the current Facebook Page." />;
  }
  if (!currentPageId) {
    return <Alert type="info" showIcon message="No Facebook Page selected" description="Open Facebook settings and select a page before viewing Orders." />;
  }

  return (
    <div className="order-operations-page">
      <div className="order-operations-header">
        <div>
          <Typography.Title level={2}>Orders</Typography.Title>
          <Typography.Text type="secondary">Search, inspect, and operate Orders for the current Facebook Page.</Typography.Text>
        </div>
        <Space wrap>
          <Tag color="blue" icon={<ShoppingCartOutlined />}>{pagination?.total ?? 0} orders</Tag>
          {currentPageName ? <Tag>{currentPageName}</Tag> : null}
        </Space>
      </div>

      <section className="order-operations-section">
        <div className="order-queue-section">
          <div className="order-queue-heading">
            <div>
              <Typography.Title level={5}>Operational queues</Typography.Title>
              <Typography.Text type="secondary">
                Queue presets are derived views and may overlap.
              </Typography.Text>
            </div>
            {hasActiveFilters ? <Button onClick={clearFilters}>Clear filters</Button> : null}
          </div>
          <div className="order-queue-bar" role="group" aria-label="Operational Order queues">
            {queueOptions.map((option) => (
              <Button
                key={option.value}
                type={queue === option.value ? "primary" : "default"}
                danger={option.value === "shipping_issue" && queue === option.value}
                aria-pressed={queue === option.value}
                onClick={() => {
                  setQueue(option.value);
                  setPage(1);
                }}
              >
                {option.label}
                {operationalSummary ? ` (${operationalSummary[option.value]})` : ""}
              </Button>
            ))}
          </div>
          {operationalSummaryQuery.isError ? (
            <Alert
              type="warning"
              showIcon
              message="Queue counts are unavailable."
              action={<Button onClick={() => void operationalSummaryQuery.refetch()}>Retry</Button>}
            />
          ) : null}
        </div>
        <div className="order-operations-toolbar">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="Search Order number, Customer name, phone, email, address, or note"
          />
          <Select<OrderFilter> value={orderStatus} aria-label="Filter by Order status" options={orderFilterOptions} onChange={(value) => { setOrderStatus(value); setPage(1); }} />
          <Select<PaymentFilter> value={paymentStatus} aria-label="Filter by payment status" options={paymentFilterOptions} onChange={(value) => { setPaymentStatus(value); setPage(1); }} />
          <Select<ShippingFilter> value={shippingStatus} aria-label="Filter by shipping status" options={shippingFilterOptions} onChange={(value) => { setShippingStatus(value); setPage(1); }} />
        </div>

        {ordersQuery.isLoading ? (
          <div className="order-page-loading"><Spin /></div>
        ) : ordersQuery.isError ? (
          <Alert type="error" showIcon message="Unable to load Orders." description={getReadableOrderError(ordersQuery.error)} action={<Button onClick={() => void ordersQuery.refetch()}>Retry</Button>} />
        ) : orders.length === 0 ? (
          <Empty description={hasActiveFilters ? "No orders match the current filters." : "No orders"} />
        ) : (
          <>
            <Table<OrderListItem> rowKey="uuid" columns={columns} dataSource={orders} pagination={false} loading={ordersQuery.isFetching} scroll={{ x: 1370 }} />
            {pagination ? (
              <div className="order-operations-pagination">
                <Typography.Text type="secondary">Page {pagination.page} of {Math.max(Math.ceil(pagination.total / pagination.page_size), 1)} · {pagination.total} total</Typography.Text>
                <Pagination current={pagination.page} pageSize={pagination.page_size} total={pagination.total} showSizeChanger={false} onChange={setPage} />
              </div>
            ) : null}
          </>
        )}
      </section>

      <OrderOperationsDetail
        open={Boolean(selectedOrderUuid)}
        order={detailQuery.data ?? null}
        loading={detailQuery.isLoading}
        loadError={detailQuery.isError ? getReadableOrderError(detailQuery.error) : null}
        operationError={operationError}
        shipments={shipmentsQuery.data?.items ?? []}
        shipmentsLoading={shipmentsQuery.isLoading}
        shipmentsError={shipmentsQuery.isError ? getReadableOrderError(shipmentsQuery.error) : null}
        activityItems={timelineQuery.data?.items ?? []}
        activityLoading={timelineQuery.isLoading}
        activityError={timelineQuery.isError ? getReadableOrderError(timelineQuery.error) : null}
        updating={updateMutation.isPending || shippingMutation.isPending || createShipmentMutation.isPending || shipmentStatusMutation.isPending || shipmentTrackingMutation.isPending}
        onClose={() => { setSelectedOrderUuid(null); setOperationError(null); }}
        onRetry={() => void detailQuery.refetch()}
        onRetryActivity={() => void timelineQuery.refetch()}
        onOpenCustomer={(customerUuid) => navigate(`/customers/${encodeURIComponent(customerUuid)}`)}
        onUpdate={submitUpdate}
        onUpdateShipping={submitShippingUpdate}
        onLifecycleChange={requestLifecycleChange}
        onCreateShipment={submitCreateShipment}
        onShipmentStatusChange={submitShipmentStatus}
        onShipmentTrackingUpdate={submitShipmentTracking}
      />
    </div>
  );
}

const orderFilterOptions: Array<{ label: string; value: OrderFilter }> = [
  { label: "All Orders", value: "all" }, { label: "Draft", value: "draft" }, { label: "Confirmed", value: "confirmed" }, { label: "Cancelled", value: "cancelled" }
];
const queueOptions: Array<{ label: string; value: OrderQueueSelection }> = [
  { label: "All", value: "all" },
  { label: "Drafts", value: "draft" },
  { label: "Needs payment", value: "needs_payment" },
  { label: "Needs packing", value: "needs_packing" },
  { label: "Packed", value: "packed" },
  { label: "In transit", value: "in_transit" },
  { label: "Shipping issue", value: "shipping_issue" },
  { label: "Cancelled", value: "cancelled" }
];
const paymentFilterOptions: Array<{ label: string; value: PaymentFilter }> = [
  { label: "All payments", value: "all" }, { label: "Unpaid", value: "unpaid" }, { label: "Partial", value: "partial" }, { label: "Paid", value: "paid" }, { label: "Refunded", value: "refunded" }
];
const shippingFilterOptions: Array<{ label: string; value: ShippingFilter }> = [
  { label: "All shipping", value: "all" }, { label: "Pending", value: "pending" }, { label: "Packed", value: "packed" }, { label: "Shipped", value: "shipped" }, { label: "Delivered", value: "delivered" }, { label: "Cancelled", value: "cancelled" }
];

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatMoney(value: string, currency: string): string {
  const amount = Number(value);
  return `${Number.isFinite(amount) ? amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value} ${currency}`;
}

function getHttpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) {
    return undefined;
  }
  return (error as { response?: { status?: number } }).response?.status;
}

function getReadableOrderError(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response;
    if (typeof response?.data?.detail === "string") {
      return response.data.detail;
    }
    if (response?.status === 409) {
      return "Stock is no longer sufficient. Review Product inventory before confirming again.";
    }
    if (response?.status === 422) {
      return "This Order transition is not allowed.";
    }
  }
  return error instanceof Error ? error.message : "Check your connection and try again.";
}
