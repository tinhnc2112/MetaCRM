import {
  DeleteOutlined,
  EditOutlined,
  FileTextOutlined,
  MessageOutlined,
  ShoppingCartOutlined,
  SwapOutlined,
  SaveOutlined,
  TeamOutlined,
  TagOutlined
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Alert, Avatar, Badge, Button, Empty, Input, List, Pagination, Select, Space, Spin, Statistic, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { getCustomerOrderSummary, getOrder, listCustomerOrders } from "../services/orderService";
import type {
  CustomerProfileResponse,
  CustomerNoteSaveRequest,
  CustomerTag
} from "../types/customer";
import type { CustomerOrderSummary, OrderListItem, OrderResponse, OrderStatus } from "../types/order";

const ORDER_PAGE_SIZE = 5;
const ORDER_STATUS_OPTIONS: Array<{ label: string; value: "all" | OrderStatus }> = [
  { label: "All", value: "all" },
  { label: "Draft", value: "draft" },
  { label: "Confirmed", value: "confirmed" },
  { label: "Cancelled", value: "cancelled" }
];

type CustomerProfilePanelProps = {
  profile: CustomerProfileResponse | null;
  currentPageId: string | null;
  pageTags: CustomerTag[];
  loading: boolean;
  error: boolean;
  savingNote: boolean;
  savingTag: boolean;
  onSaveNote: (input: CustomerNoteSaveRequest) => Promise<void>;
  onDeleteNote: (noteId: string) => Promise<void>;
  onAssignTag: (tagId: number) => Promise<void>;
  onRemoveTag: (tagId: number) => Promise<void>;
  onManageTags: () => void;
  onOpenCustomer?: (customerId: string) => void;
  onOpenConversation?: (conversationId: string) => void;
  onSelectConversation?: (conversationId: string) => void;
};

export function CustomerProfilePanel({
  profile,
  currentPageId,
  pageTags,
  loading,
  error,
  savingNote,
  savingTag,
  onSaveNote,
  onDeleteNote,
  onAssignTag,
  onRemoveTag,
  onManageTags,
  onOpenCustomer,
  onOpenConversation,
  onSelectConversation
}: CustomerProfilePanelProps) {
  const [noteId, setNoteId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [selectedTagId, setSelectedTagId] = useState<number | null>(null);
  const [orderPage, setOrderPage] = useState(1);
  const [orderStatus, setOrderStatus] = useState<"all" | OrderStatus>("all");
  const [selectedOrderUuid, setSelectedOrderUuid] = useState<string | null>(null);

  const conversation = profile?.conversation ?? null;
  const customer = profile?.customer ?? null;
  const notes = profile?.notes ?? [];
  const timeline = profile?.timeline ?? [];
  const assignedTags = profile?.tags ?? [];
  const customerConversations = profile?.conversations ?? [];

  useEffect(() => {
    setNoteId(null);
    setDraft("");
    setSelectedTagId(null);
  }, [conversation?.uuid]);

  useEffect(() => {
    const assignedTagIds = new Set(assignedTags.map((tag) => tag.id));
    const availableTags = pageTags.filter((tag) => !assignedTagIds.has(tag.id));
    if (availableTags.length === 0) {
      setSelectedTagId(null);
      return;
    }
    if (selectedTagId === null || !availableTags.some((tag) => tag.id === selectedTagId)) {
      setSelectedTagId(availableTags[0].id);
    }
  }, [assignedTags, pageTags, selectedTagId]);

  const headerName = useMemo(
    () => customer?.name ?? conversation?.customer_name ?? conversation?.customer_psid ?? "Customer",
    [conversation, customer]
  );
  const initial = headerName.slice(0, 1).toUpperCase();
  const customerUuid = customer?.uuid ?? null;
  const customerPhone = customer?.phone ?? null;
  const customerEmail = customer?.email ?? null;
  const orderStatusParam = orderStatus === "all" ? undefined : orderStatus;

  useEffect(() => {
    setOrderPage(1);
    setOrderStatus("all");
    setSelectedOrderUuid(null);
  }, [currentPageId, customerUuid]);

  const ordersQuery = useQuery({
    queryKey: ["customer-orders", currentPageId, customerUuid, orderPage, ORDER_PAGE_SIZE, orderStatusParam ?? "all"],
    queryFn: () =>
      listCustomerOrders(customerUuid as string, {
        page: orderPage,
        pageSize: ORDER_PAGE_SIZE,
        status: orderStatusParam
      }),
    enabled: Boolean(currentPageId && customerUuid)
  });

  const orderSummaryQuery = useQuery({
    queryKey: ["customer-order-summary", currentPageId, customerUuid],
    queryFn: () => getCustomerOrderSummary(customerUuid as string),
    enabled: Boolean(currentPageId && customerUuid)
  });

  const orderDetailQuery = useQuery({
    queryKey: ["order-detail", currentPageId, selectedOrderUuid],
    queryFn: () => getOrder(selectedOrderUuid as string),
    enabled: Boolean(currentPageId && selectedOrderUuid)
  });

  const availableTags = useMemo(() => {
    const assignedTagIds = new Set(assignedTags.map((tag) => tag.id));
    return pageTags.filter((tag) => !assignedTagIds.has(tag.id));
  }, [assignedTags, pageTags]);

  const handleSave = async () => {
    const content = draft.trim();
    if (!content) {
      return;
    }
    await onSaveNote({ noteId, content });
    setNoteId(null);
    setDraft("");
  };

  const handleAssignTag = async () => {
    if (selectedTagId === null) {
      return;
    }
    await onAssignTag(selectedTagId);
    setSelectedTagId(null);
  };

  if (!conversation && loading) {
    return (
      <section className="messenger-profile-panel">
        <div className="messenger-loading">
          <Spin />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="messenger-profile-panel">
        <Empty description="Could not load customer profile" />
      </section>
    );
  }

  if (!conversation) {
    return (
      <section className="messenger-profile-panel">
        <Empty description="Select a conversation to view the customer profile" />
      </section>
    );
  }

  return (
    <section className="messenger-profile-panel">
      <header className="messenger-profile-header">
        <div className="messenger-profile-identity">
          {conversation.customer_avatar_url ? (
            <Avatar size={56} src={conversation.customer_avatar_url} />
          ) : (
            <Avatar size={56}>{initial}</Avatar>
          )}
          <div>
            <Typography.Title level={4}>{headerName}</Typography.Title>
            <Typography.Text type="secondary">
              {customerUuid ? `Customer ${customerUuid}` : conversation.customer_psid}
            </Typography.Text>
          </div>
        </div>
        <Space direction="vertical" align="end" size={8}>
          <Badge count={conversation.unread_count} overflowCount={99} />
          <Space wrap>
            {customerUuid && onOpenCustomer ? (
              <Button size="small" icon={<TeamOutlined />} onClick={() => onOpenCustomer(customerUuid)}>
                Open customer
              </Button>
            ) : null}
            {onOpenConversation ? (
              <Button size="small" icon={<SwapOutlined />} onClick={() => onOpenConversation(conversation.uuid)}>
                Open in Messenger
              </Button>
            ) : null}
          </Space>
        </Space>
      </header>

      <div className="messenger-profile-meta">
        <div>
          <span className="messenger-profile-label">Customer UUID</span>
          <Typography.Text copyable={customerUuid ? { text: customerUuid } : undefined}>
            {customerUuid ?? "Unavailable"}
          </Typography.Text>
        </div>
        <div>
          <span className="messenger-profile-label">Phone</span>
          <Typography.Text copyable={customerPhone ? { text: customerPhone } : undefined}>
            {customerPhone ?? "Unavailable"}
          </Typography.Text>
        </div>
        <div>
          <span className="messenger-profile-label">Email</span>
          <Typography.Text copyable={customerEmail ? { text: customerEmail } : undefined}>
            {customerEmail ?? "Unavailable"}
          </Typography.Text>
        </div>
        <div>
          <span className="messenger-profile-label">Last interaction</span>
          <Typography.Text>{formatTimestamp(conversation.last_message_at)}</Typography.Text>
        </div>
        <div>
          <span className="messenger-profile-label">Conversation UUID</span>
          <Typography.Text copyable>{conversation.uuid}</Typography.Text>
        </div>
        <div>
          <span className="messenger-profile-label">PSID</span>
          <Typography.Text copyable>{conversation.customer_psid}</Typography.Text>
        </div>
      </div>

      {customerConversations.length > 1 ? (
        <section className="messenger-profile-section">
          <div className="messenger-profile-section-header">
            <Typography.Title level={5}>Conversations</Typography.Title>
          </div>
          <List
            dataSource={customerConversations}
            renderItem={(item) => {
              const displayName = item.customer_name ?? item.customer_psid;
              const isCurrent = item.uuid === conversation.uuid;
              return (
                <List.Item className={isCurrent ? "messenger-conversation selected" : "messenger-conversation"}>
                  <List.Item.Meta
                    avatar={
                      item.customer_avatar_url ? (
                        <Avatar src={item.customer_avatar_url} />
                      ) : (
                        <Avatar>{displayName.slice(0, 1).toUpperCase()}</Avatar>
                      )
                    }
                    title={
                      <div className="messenger-conversation-title">
                        <span>{displayName}</span>
                        {item.unread_count > 0 ? <Badge count={item.unread_count} /> : null}
                      </div>
                    }
                    description={
                      <div className="messenger-conversation-meta">
                        <span>{item.customer_psid}</span>
                        <span>{formatTimestamp(item.last_message_at)}</span>
                      </div>
                    }
                  />
                  <Space>
                    {isCurrent ? <Tag color="blue">Current</Tag> : null}
                    {onSelectConversation && !isCurrent ? (
                      <Button size="small" onClick={() => onSelectConversation(item.uuid)}>
                        Use
                      </Button>
                    ) : null}
                    {onOpenConversation ? (
                      <Button size="small" onClick={() => onOpenConversation(item.uuid)}>
                        Open
                      </Button>
                    ) : null}
                  </Space>
                </List.Item>
              );
            }}
          />
        </section>
      ) : null}

      <section className="messenger-profile-section">
        <div className="messenger-profile-section-header">
          <Typography.Title level={5}>Orders</Typography.Title>
          <Select
            size="small"
            value={orderStatus}
            options={ORDER_STATUS_OPTIONS}
            onChange={(value) => {
              setOrderStatus(value);
              setOrderPage(1);
            }}
            disabled={!customerUuid || ordersQuery.isLoading}
            aria-label="Filter customer orders by status"
          />
        </div>

        {!customerUuid ? (
          <Empty description="Order history is unavailable until this profile has a customer UUID" />
        ) : ordersQuery.isLoading ? (
          <div className="messenger-profile-inline-loading">
            <Spin size="small" />
          </div>
        ) : ordersQuery.isError ? (
          <Alert type="error" showIcon message="Could not load order history." />
        ) : (ordersQuery.data?.items ?? []).length === 0 ? (
          <Empty description={orderStatus === "all" ? "No orders yet" : `No ${orderStatus} orders found`} />
        ) : (
          <CustomerOrdersList
            orders={ordersQuery.data?.items ?? []}
            total={ordersQuery.data?.meta.total ?? 0}
            page={ordersQuery.data?.meta.page ?? orderPage}
            pageSize={ordersQuery.data?.meta.page_size ?? ORDER_PAGE_SIZE}
            loading={ordersQuery.isFetching}
            summary={orderSummaryQuery.data ?? null}
            summaryLoading={orderSummaryQuery.isLoading}
            summaryError={orderSummaryQuery.isError}
            selectedOrderUuid={selectedOrderUuid}
            orderDetail={orderDetailQuery.data ?? null}
            orderDetailLoading={orderDetailQuery.isLoading}
            orderDetailError={orderDetailQuery.isError}
            onPageChange={setOrderPage}
            onSelectOrder={(orderUuid) => setSelectedOrderUuid((current) => (current === orderUuid ? null : orderUuid))}
            onOpenConversation={onOpenConversation}
          />
        )}
      </section>

      <section className="messenger-profile-section">
        <div className="messenger-profile-section-header">
          <Typography.Title level={5}>Tags</Typography.Title>
          <Button size="small" onClick={onManageTags}>
            Manage tags
          </Button>
        </div>
        {assignedTags.length === 0 ? (
          <Empty description="No tags assigned yet" />
        ) : (
          <div className="messenger-tag-list">
            {assignedTags.map((tag) => (
              <Tag
                key={tag.id}
                closable
                onClose={(event) => {
                  event.preventDefault();
                  void onRemoveTag(tag.id);
                }}
              >
                {tag.name}
              </Tag>
            ))}
          </div>
        )}
        <div className="messenger-tag-assigner">
          <Select
            showSearch
            placeholder={availableTags.length === 0 ? "No more tags available" : "Select a tag to assign"}
            optionFilterProp="label"
            value={selectedTagId ?? undefined}
            onChange={(value) => setSelectedTagId(value)}
            options={availableTags.map((tag) => ({
              value: tag.id,
              label: tag.name
            }))}
            disabled={availableTags.length === 0}
          />
          <Button type="primary" onClick={() => void handleAssignTag()} loading={savingTag} disabled={selectedTagId === null}>
            Assign tag
          </Button>
        </div>
      </section>

      <section className="messenger-profile-section">
        <div className="messenger-profile-section-header">
          <Typography.Title level={5}>Internal Notes</Typography.Title>
        </div>
        <div className="messenger-note-editor">
          <Input.TextArea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Write an internal note..."
            autoSize={{ minRows: 4, maxRows: 8 }}
          />
          <Space className="messenger-note-editor-actions">
            <Button
              icon={<SaveOutlined />}
              type="primary"
              onClick={() => void handleSave()}
              loading={savingNote}
              disabled={!draft.trim()}
            >
              {noteId ? "Update note" : "Save note"}
            </Button>
            {noteId ? (
              <Button
                onClick={() => {
                  setNoteId(null);
                  setDraft("");
                }}
              >
                Cancel
              </Button>
            ) : null}
          </Space>
        </div>

        {notes.length === 0 ? (
          <Empty description="No internal notes yet" />
        ) : (
          <List
            dataSource={notes}
            renderItem={(note) => (
              <List.Item className="messenger-note-item">
                <div className="messenger-note-card">
                  <div className="messenger-note-content">{note.content}</div>
                  <div className="messenger-note-footer">
                    <Typography.Text type="secondary">{formatTimestamp(note.created_at)}</Typography.Text>
                    <Space size={8}>
                      <Button
                        icon={<EditOutlined />}
                        size="small"
                        onClick={() => {
                          setNoteId(note.id);
                          setDraft(note.content);
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        icon={<DeleteOutlined />}
                        size="small"
                        danger
                        onClick={() => void onDeleteNote(note.id)}
                      >
                        Delete
                      </Button>
                    </Space>
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
      </section>

      <section className="messenger-profile-section">
        <div className="messenger-profile-section-header">
          <Typography.Title level={5}>Timeline</Typography.Title>
        </div>
        {timeline.length === 0 ? (
          <Empty description="No timeline items yet" />
        ) : (
          <div className="messenger-timeline">
            {timeline.map((item) => {
              const isNote = item.type === "note";
              const isTag = item.type === "tag";
              const label = isTag
                ? item.action === "removed"
                  ? `Tag removed${item.tag_name ? `: ${item.tag_name}` : ""}`
                  : `Tag added${item.tag_name ? `: ${item.tag_name}` : ""}`
                : isNote
                  ? "Internal note added"
                  : item.is_from_page
                    ? "Agent replied"
                    : "Customer sent message";
              const color = isTag ? (item.action === "removed" ? "volcano" : "purple") : isNote ? "gold" : item.is_from_page ? "blue" : "green";
              const icon = isTag ? <TagOutlined /> : isNote ? <FileTextOutlined /> : <MessageOutlined />;
              return (
                <article key={`${item.type}-${item.timestamp}-${item.preview ?? item.content ?? ""}`} className="messenger-timeline-item">
                  <div className="messenger-timeline-header">
                    <Tag color={color} icon={icon}>
                      {label}
                    </Tag>
                    <Typography.Text type="secondary">{formatTimestamp(item.timestamp)}</Typography.Text>
                  </div>
                  <div className="messenger-timeline-body">{item.preview ?? item.content ?? "No content"}</div>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </section>
  );
}

function CustomerOrdersList({
  orders,
  total,
  page,
  pageSize,
  loading,
  summary,
  summaryLoading,
  summaryError,
  selectedOrderUuid,
  orderDetail,
  orderDetailLoading,
  orderDetailError,
  onPageChange,
  onSelectOrder,
  onOpenConversation
}: {
  orders: OrderListItem[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  summary: CustomerOrderSummary | null;
  summaryLoading: boolean;
  summaryError: boolean;
  selectedOrderUuid: string | null;
  orderDetail: OrderResponse | null;
  orderDetailLoading: boolean;
  orderDetailError: boolean;
  onPageChange: (page: number) => void;
  onSelectOrder: (orderUuid: string) => void;
  onOpenConversation?: (conversationId: string) => void;
}) {
  const totalShown = orders.reduce((sum, order) => sum + parseMoney(order.total_amount), 0);
  const latestShown = orders
    .map((order) => new Date(order.created_at))
    .filter((date) => !Number.isNaN(date.getTime()))
    .sort((left, right) => right.getTime() - left.getTime())[0];
  const currency = orders[0]?.currency ?? "";

  return (
    <div className="customer-orders">
      <div className="customer-orders-summary">
        {summaryLoading ? (
          <div className="customer-orders-summary-loading">
            <Spin size="small" />
          </div>
        ) : summaryError || !summary ? (
          <>
            <Statistic title="Orders shown" value={orders.length} />
            <Statistic title="Total shown" value={formatMoney(totalShown, currency)} />
            <Statistic title="Latest shown" value={latestShown ? latestShown.toLocaleDateString() : "Unknown"} />
          </>
        ) : (
          <>
            <Statistic title="Orders" value={summary.order_count} />
            <Statistic title="Total spend" value={formatMoney(parseMoney(summary.total_spend), currency)} />
            <Statistic title="Latest order" value={formatDate(summary.latest_order_at)} />
          </>
        )}
      </div>

      <List
        dataSource={orders}
        loading={loading}
        renderItem={(order) => (
          <List.Item className="customer-order-item">
            <article className="customer-order-card">
              <div className="customer-order-card-header">
                <div>
                  <Typography.Text strong>{order.order_number || "Order #"}</Typography.Text>
                  <div className="customer-order-date">{formatTimestamp(order.created_at)}</div>
                </div>
                <Tag color={getOrderStatusColor(order.status)} icon={<ShoppingCartOutlined />}>
                  {labelize(order.status)}
                </Tag>
              </div>

              <div className="customer-order-grid">
                <OrderField label="Payment" value={labelize(order.payment_status)} />
                <OrderField label="Shipping" value={labelize(order.shipping_status)} />
                <OrderField label="Total" value={`${safeText(order.total_amount)} ${safeText(order.currency)}`.trim()} />
                <OrderField label="Items" value={String(order.item_count)} />
              </div>

              {order.note ? (
                <Typography.Paragraph className="customer-order-note" ellipsis={{ rows: 2 }}>
                  {order.note}
                </Typography.Paragraph>
              ) : null}

              <Space wrap>
                <Button size="small" onClick={() => onSelectOrder(order.uuid)}>
                  {selectedOrderUuid === order.uuid ? "Hide details" : "View details"}
                </Button>
                {order.conversation_uuid && onOpenConversation ? (
                  <Button size="small" type="link" onClick={() => onOpenConversation(order.conversation_uuid as string)}>
                    Open conversation
                  </Button>
                ) : null}
              </Space>

              {selectedOrderUuid === order.uuid ? (
                <OrderDetailPanel
                  order={orderDetail}
                  loading={orderDetailLoading}
                  error={orderDetailError}
                  onOpenConversation={onOpenConversation}
                />
              ) : null}
            </article>
          </List.Item>
        )}
      />

      <div className="customer-orders-pagination">
        <Pagination
          size="small"
          current={page}
          pageSize={pageSize}
          total={total}
          onChange={onPageChange}
          showSizeChanger={false}
          disabled={loading}
        />
      </div>
    </div>
  );
}

function OrderField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="messenger-profile-label">{label}</span>
      <Typography.Text>{safeText(value)}</Typography.Text>
    </div>
  );
}

function OrderDetailPanel({
  order,
  loading,
  error,
  onOpenConversation
}: {
  order: OrderResponse | null;
  loading: boolean;
  error: boolean;
  onOpenConversation?: (conversationId: string) => void;
}) {
  if (loading) {
    return (
      <div className="customer-order-detail">
        <Spin size="small" />
      </div>
    );
  }

  if (error) {
    return <Alert type="error" showIcon message="Could not load order details." />;
  }

  if (!order) {
    return <Empty description="No order detail loaded" />;
  }

  return (
    <div className="customer-order-detail">
      <div className="customer-order-detail-grid">
        <OrderField label="Subtotal" value={`${safeText(order.subtotal_amount)} ${safeText(order.currency)}`.trim()} />
        <OrderField label="Discount" value={`${safeText(order.discount_amount)} ${safeText(order.currency)}`.trim()} />
        <OrderField label="Shipping fee" value={`${safeText(order.shipping_fee)} ${safeText(order.currency)}`.trim()} />
        <OrderField label="Total" value={`${safeText(order.total_amount)} ${safeText(order.currency)}`.trim()} />
      </div>

      {order.shipping_address ? (
        <div>
          <span className="messenger-profile-label">Shipping address</span>
          <Typography.Text>{order.shipping_address}</Typography.Text>
        </div>
      ) : null}

      {order.note ? (
        <div>
          <span className="messenger-profile-label">Order note</span>
          <Typography.Paragraph className="customer-order-note">{order.note}</Typography.Paragraph>
        </div>
      ) : null}

      <div>
        <span className="messenger-profile-label">Items</span>
        {order.items.length === 0 ? (
          <Empty description="No items found for this order" />
        ) : (
          <div className="customer-order-items">
            {order.items.map((item) => (
              <div key={item.uuid} className="customer-order-item-row">
                <div>
                  <Typography.Text strong>{safeText(item.item_name)}</Typography.Text>
                  <div className="customer-order-date">{item.sku ? `SKU ${item.sku}` : "No SKU"}</div>
                  {item.note ? <div className="customer-order-date">{item.note}</div> : null}
                </div>
                <div className="customer-order-item-amount">
                  <Typography.Text>
                    {item.quantity} x {safeText(item.unit_price)}
                  </Typography.Text>
                  <Typography.Text strong>{safeText(item.line_total)}</Typography.Text>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {order.conversation_uuid && onOpenConversation ? (
        <Button size="small" type="link" onClick={() => onOpenConversation(order.conversation_uuid as string)}>
          Open linked conversation
        </Button>
      ) : null}
    </div>
  );
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatDate(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

function parseMoney(value: string | number | null): number {
  if (value === null) {
    return 0;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatMoney(value: number, currency: string): string {
  const amount = Number.isFinite(value)
    ? value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "0.00";
  return `${amount} ${currency}`.trim();
}

function safeText(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "Unavailable";
  }
  return String(value);
}

function labelize(value: string | null | undefined): string {
  if (!value) {
    return "Unavailable";
  }
  return value
    .split("_")
    .map((part) => part.slice(0, 1).toUpperCase() + part.slice(1))
    .join(" ");
}

function getOrderStatusColor(status: OrderStatus): string {
  if (status === "confirmed") {
    return "green";
  }
  if (status === "cancelled") {
    return "red";
  }
  return "blue";
}
