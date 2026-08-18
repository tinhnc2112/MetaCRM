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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App as AntApp,
  Avatar,
  Badge,
  Button,
  Divider,
  Empty,
  Input,
  InputNumber,
  List,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography
} from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { createOrder, getCustomerOrderSummary, getOrder, listCustomerOrders, updateOrder } from "../services/orderService";
import type {
  CustomerProfileResponse,
  CustomerNoteSaveRequest,
  CustomerTag
} from "../types/customer";
import type {
  CustomerOrderSummary,
  OrderCreatePayload,
  OrderListItem,
  OrderResponse,
  OrderStatus,
  OrderUpdatePayload,
  PaymentStatus,
  ShippingStatus
} from "../types/order";

const ORDER_PAGE_SIZE = 5;
const ORDER_STATUS_OPTIONS: Array<{ label: string; value: "all" | OrderStatus }> = [
  { label: "All", value: "all" },
  { label: "Draft", value: "draft" },
  { label: "Confirmed", value: "confirmed" },
  { label: "Cancelled", value: "cancelled" }
];
const ORDER_LIFECYCLE_STATUS_OPTIONS: Array<{ label: string; value: OrderStatus; disabled?: boolean }> = [
  { label: "Draft", value: "draft" },
  { label: "Confirmed", value: "confirmed" },
  { label: "Cancelled", value: "cancelled", disabled: true }
];
const PAYMENT_STATUS_OPTIONS: Array<{ label: string; value: PaymentStatus }> = [
  { label: "Unpaid", value: "unpaid" },
  { label: "Partial", value: "partial" },
  { label: "Paid", value: "paid" },
  { label: "Refunded", value: "refunded" }
];
const SHIPPING_STATUS_OPTIONS: Array<{ label: string; value: ShippingStatus }> = [
  { label: "Pending", value: "pending" },
  { label: "Packed", value: "packed" },
  { label: "Shipped", value: "shipped" },
  { label: "Delivered", value: "delivered" },
  { label: "Cancelled", value: "cancelled" }
];

type CreateOrderItemDraft = {
  item_name: string;
  sku: string;
  quantity: number;
  unit_price: number;
  note: string;
};

type CreateOrderDraft = {
  currency: string;
  discount_amount: number;
  shipping_fee: number;
  shipping_address: string;
  note: string;
  items: CreateOrderItemDraft[];
};

type CreateOrderMutationInput = {
  payload: OrderCreatePayload;
  pageId: string;
  customerUuid: string;
  contextKey: string;
};

type OrderUpdateMutationInput = {
  orderUuid: string;
  payload: OrderUpdatePayload;
  pageId: string;
  customerUuid: string;
  contextKey: string;
  successMessage: string;
};

type OrderLifecycleDraft = {
  status: OrderStatus;
  payment_status: PaymentStatus;
  shipping_status: ShippingStatus;
};

type CustomerProfilePanelProps = {
  profile: CustomerProfileResponse | null;
  currentPageId: string | null;
  createOrderConversationUuid?: string | null;
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
  createOrderConversationUuid,
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
  const queryClient = useQueryClient();
  const { message, modal } = AntApp.useApp();
  const [noteId, setNoteId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [selectedTagId, setSelectedTagId] = useState<number | null>(null);
  const [orderPage, setOrderPage] = useState(1);
  const [orderStatus, setOrderStatus] = useState<"all" | OrderStatus>("all");
  const [selectedOrderUuid, setSelectedOrderUuid] = useState<string | null>(null);
  const [createOrderOpen, setCreateOrderOpen] = useState(false);
  const [createOrderError, setCreateOrderError] = useState<string | null>(null);
  const [createOrderDraft, setCreateOrderDraft] = useState<CreateOrderDraft>(() => buildEmptyOrderDraft());
  const [orderUpdateError, setOrderUpdateError] = useState<string | null>(null);

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
  const resolvedCreateOrderConversationUuid = createOrderConversationUuid ?? null;
  const createOrderContextKey = JSON.stringify([
    currentPageId,
    customerUuid,
    resolvedCreateOrderConversationUuid
  ]);
  const createOrderContextRef = useRef(createOrderContextKey);
  const createOrderSubmitLockRef = useRef(false);
  const orderUpdateContextKey = JSON.stringify([currentPageId, customerUuid, selectedOrderUuid]);
  const orderUpdateContextRef = useRef(orderUpdateContextKey);
  const orderUpdateSubmitLockRef = useRef(false);
  createOrderContextRef.current = createOrderContextKey;
  orderUpdateContextRef.current = orderUpdateContextKey;

  useEffect(() => {
    setOrderPage(1);
    setOrderStatus("all");
    setSelectedOrderUuid(null);
    setCreateOrderOpen(false);
    setCreateOrderError(null);
    setCreateOrderDraft(buildEmptyOrderDraft());
    setOrderUpdateError(null);
  }, [currentPageId, customerUuid, resolvedCreateOrderConversationUuid]);

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

  const createOrderMutation = useMutation({
    mutationFn: ({ payload }: CreateOrderMutationInput) => createOrder(payload),
    onSuccess: async (order, input) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["customer-orders", input.pageId, input.customerUuid] }),
        queryClient.invalidateQueries({ queryKey: ["customer-order-summary", input.pageId, input.customerUuid] }),
        queryClient.invalidateQueries({ queryKey: ["order-detail", input.pageId] })
      ]);
      if (createOrderContextRef.current !== input.contextKey) {
        return;
      }
      setCreateOrderOpen(false);
      setCreateOrderError(null);
      setCreateOrderDraft(buildEmptyOrderDraft());
      setOrderPage(1);
      setOrderStatus("all");
      setSelectedOrderUuid(order.uuid);
      void message.success(`Created order ${order.order_number}`);
    },
    onError: (error, input) => {
      if (createOrderContextRef.current === input.contextKey) {
        setCreateOrderError(getReadableError(error));
      }
    }
  });

  const orderUpdateMutation = useMutation({
    mutationFn: ({ orderUuid, payload }: OrderUpdateMutationInput) => updateOrder(orderUuid, payload),
    onSuccess: async (_, input) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["customer-orders", input.pageId, input.customerUuid] }),
        queryClient.invalidateQueries({ queryKey: ["customer-order-summary", input.pageId, input.customerUuid] }),
        queryClient.invalidateQueries({ queryKey: ["order-detail", input.pageId, input.orderUuid] })
      ]);
      if (orderUpdateContextRef.current !== input.contextKey) {
        return;
      }
      setOrderUpdateError(null);
      void message.success(input.successMessage);
    },
    onError: (error, input) => {
      if (orderUpdateContextRef.current === input.contextKey) {
        setOrderUpdateError(getReadableError(error, "Could not update order. Please try again."));
      }
    }
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

  const handleSubmitOrder = async () => {
    if (createOrderSubmitLockRef.current || createOrderMutation.isPending) {
      return;
    }
    if (!customerUuid || !currentPageId || !conversation) {
      setCreateOrderError("Customer profile is not ready for order creation.");
      return;
    }

    const validationError = validateCreateOrderDraft(createOrderDraft);
    if (validationError) {
      setCreateOrderError(validationError);
      return;
    }

    const payload: OrderCreatePayload = {
      customer_uuid: customerUuid,
      currency: createOrderDraft.currency.trim().toUpperCase() || "VND",
      discount_amount: createOrderDraft.discount_amount,
      shipping_fee: createOrderDraft.shipping_fee,
      shipping_address: normaliseOptionalText(createOrderDraft.shipping_address),
      note: normaliseOptionalText(createOrderDraft.note),
      items: createOrderDraft.items.map((item) => ({
        item_name: item.item_name.trim(),
        sku: normaliseOptionalText(item.sku),
        quantity: item.quantity,
        unit_price: item.unit_price,
        note: normaliseOptionalText(item.note)
      }))
    };
    if (resolvedCreateOrderConversationUuid) {
      payload.conversation_uuid = resolvedCreateOrderConversationUuid;
    }

    setCreateOrderError(null);
    createOrderSubmitLockRef.current = true;
    try {
      await createOrderMutation.mutateAsync({
        payload,
        pageId: currentPageId,
        customerUuid,
        contextKey: createOrderContextKey
      });
    } catch {
      // The mutation callback keeps the form open and renders the readable error.
    } finally {
      createOrderSubmitLockRef.current = false;
    }
  };

  const buildOrderUpdateInput = (
    orderUuid: string,
    payload: OrderUpdatePayload,
    successMessage: string
  ): OrderUpdateMutationInput | null => {
    const loadedOrder = orderDetailQuery.data;
    if (
      !currentPageId ||
      !customerUuid ||
      !selectedOrderUuid ||
      selectedOrderUuid !== orderUuid ||
      loadedOrder?.uuid !== orderUuid ||
      loadedOrder.customer_uuid !== customerUuid
    ) {
      setOrderUpdateError("Order context is no longer available. Reopen the order and try again.");
      return null;
    }
    return {
      orderUuid,
      payload,
      pageId: currentPageId,
      customerUuid,
      contextKey: orderUpdateContextKey,
      successMessage
    };
  };

  const executeOrderUpdate = async (input: OrderUpdateMutationInput) => {
    if (
      orderUpdateSubmitLockRef.current ||
      orderUpdateMutation.isPending ||
      orderUpdateContextRef.current !== input.contextKey
    ) {
      return;
    }
    setOrderUpdateError(null);
    orderUpdateSubmitLockRef.current = true;
    try {
      await orderUpdateMutation.mutateAsync(input);
    } catch {
      // The mutation callback renders a readable error for the active order context.
    } finally {
      orderUpdateSubmitLockRef.current = false;
    }
  };

  const handleUpdateOrder = async (orderUuid: string, payload: OrderUpdatePayload) => {
    const input = buildOrderUpdateInput(orderUuid, payload, "Order statuses updated");
    if (input) {
      await executeOrderUpdate(input);
    }
  };

  const handleCancelOrder = (orderUuid: string, orderNumber: string) => {
    const input = buildOrderUpdateInput(orderUuid, { status: "cancelled" }, `Cancelled order ${orderNumber}`);
    if (!input) {
      return;
    }
    modal.confirm({
      title: "Cancel order?",
      content: `Cancel ${orderNumber}? This order cannot be reopened. Payment status will not change automatically.`,
      okText: "Cancel order",
      okButtonProps: { danger: true },
      cancelText: "Keep order",
      onOk: () => executeOrderUpdate(input)
    });
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
          <Space wrap>
            <Button
              size="small"
              type="primary"
              icon={<ShoppingCartOutlined />}
              disabled={!customerUuid || !currentPageId || createOrderMutation.isPending}
              onClick={() => {
                setCreateOrderError(null);
                setCreateOrderOpen(true);
              }}
            >
              Create order
            </Button>
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
          </Space>
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
            orderUpdateError={orderUpdateError}
            orderUpdating={orderUpdateMutation.isPending}
            onPageChange={setOrderPage}
            onSelectOrder={(orderUuid) => {
              setOrderUpdateError(null);
              setSelectedOrderUuid((current) => (current === orderUuid ? null : orderUuid));
            }}
            onUpdateOrder={handleUpdateOrder}
            onCancelOrder={handleCancelOrder}
            onOpenConversation={onOpenConversation}
          />
        )}
      </section>

      <CreateOrderModal
        open={createOrderOpen}
        draft={createOrderDraft}
        error={createOrderError}
        submitting={createOrderMutation.isPending}
        customerUuid={customerUuid}
        conversationUuid={resolvedCreateOrderConversationUuid}
        onChange={(nextDraft) => {
          setCreateOrderDraft(nextDraft);
          setCreateOrderError(null);
        }}
        onCancel={() => {
          if (!createOrderMutation.isPending) {
            setCreateOrderOpen(false);
            setCreateOrderError(null);
            setCreateOrderDraft(buildEmptyOrderDraft());
          }
        }}
        onSubmit={() => void handleSubmitOrder()}
      />

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

function CreateOrderModal({
  open,
  draft,
  error,
  submitting,
  customerUuid,
  conversationUuid,
  onChange,
  onCancel,
  onSubmit
}: {
  open: boolean;
  draft: CreateOrderDraft;
  error: string | null;
  submitting: boolean;
  customerUuid: string | null;
  conversationUuid: string | null;
  onChange: (draft: CreateOrderDraft) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const preview = calculatePreviewTotals(draft);

  const updateDraft = (patch: Partial<CreateOrderDraft>) => {
    onChange({ ...draft, ...patch });
  };

  const updateItem = (index: number, patch: Partial<CreateOrderItemDraft>) => {
    onChange({
      ...draft,
      items: draft.items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item))
    });
  };

  const addItem = () => {
    onChange({ ...draft, items: [...draft.items, buildEmptyOrderItemDraft()] });
  };

  const removeItem = (index: number) => {
    if (draft.items.length <= 1) {
      return;
    }
    onChange({ ...draft, items: draft.items.filter((_, itemIndex) => itemIndex !== index) });
  };

  return (
    <Modal
      title="Create order"
      open={open}
      onCancel={onCancel}
      onOk={onSubmit}
      okText="Create order"
      cancelText="Cancel"
      confirmLoading={submitting}
      okButtonProps={{ disabled: !customerUuid || submitting }}
      width={760}
      destroyOnClose
    >
      <div className="create-order-form">
        {error ? <Alert type="error" showIcon message={error} /> : null}

        <div className="create-order-context">
          <OrderField label="Customer UUID" value={customerUuid ?? "Unavailable"} />
          <OrderField label="Conversation UUID" value={conversationUuid ?? "Unavailable"} />
        </div>

        <div className="create-order-grid">
          <div>
            <span className="messenger-profile-label">Currency</span>
            <Input
              value={draft.currency}
              maxLength={8}
              onChange={(event) => updateDraft({ currency: event.target.value.toUpperCase() })}
              disabled={submitting}
            />
          </div>
          <div>
            <span className="messenger-profile-label">Discount amount</span>
            <InputNumber
              min={0}
              value={draft.discount_amount}
              onChange={(value) => updateDraft({ discount_amount: normaliseNumberInput(value, 0) })}
              disabled={submitting}
              className="create-order-number-input"
            />
          </div>
          <div>
            <span className="messenger-profile-label">Shipping fee</span>
            <InputNumber
              min={0}
              value={draft.shipping_fee}
              onChange={(value) => updateDraft({ shipping_fee: normaliseNumberInput(value, 0) })}
              disabled={submitting}
              className="create-order-number-input"
            />
          </div>
        </div>

        <div>
          <span className="messenger-profile-label">Shipping address</span>
          <Input.TextArea
            value={draft.shipping_address}
            onChange={(event) => updateDraft({ shipping_address: event.target.value })}
            disabled={submitting}
            autoSize={{ minRows: 2, maxRows: 4 }}
            placeholder="Optional shipping address"
          />
        </div>

        <div>
          <span className="messenger-profile-label">Order note</span>
          <Input.TextArea
            value={draft.note}
            onChange={(event) => updateDraft({ note: event.target.value })}
            disabled={submitting}
            autoSize={{ minRows: 2, maxRows: 4 }}
            placeholder="Optional internal note"
          />
        </div>

        <Divider orientation="left">Items</Divider>

        <div className="create-order-items">
          {draft.items.map((item, index) => (
            <div key={index} className="create-order-item">
              <div className="create-order-item-header">
                <Typography.Text strong>Item {index + 1}</Typography.Text>
                <Button size="small" danger disabled={submitting || draft.items.length <= 1} onClick={() => removeItem(index)}>
                  Remove
                </Button>
              </div>
              <div className="create-order-grid">
                <div>
                  <span className="messenger-profile-label">Item name</span>
                  <Input
                    value={item.item_name}
                    onChange={(event) => updateItem(index, { item_name: event.target.value })}
                    disabled={submitting}
                    placeholder="Required"
                  />
                </div>
                <div>
                  <span className="messenger-profile-label">SKU</span>
                  <Input
                    value={item.sku}
                    onChange={(event) => updateItem(index, { sku: event.target.value })}
                    disabled={submitting}
                    placeholder="Optional"
                  />
                </div>
                <div>
                  <span className="messenger-profile-label">Quantity</span>
                  <InputNumber
                    min={1}
                    precision={0}
                    step={1}
                    value={item.quantity}
                    onChange={(value) => updateItem(index, { quantity: normaliseNumberInput(value, 1) })}
                    disabled={submitting}
                    className="create-order-number-input"
                  />
                </div>
                <div>
                  <span className="messenger-profile-label">Unit price</span>
                  <InputNumber
                    min={0}
                    value={item.unit_price}
                    onChange={(value) => updateItem(index, { unit_price: normaliseNumberInput(value, 0) })}
                    disabled={submitting}
                    className="create-order-number-input"
                  />
                </div>
              </div>
              <div>
                <span className="messenger-profile-label">Item note</span>
                <Input
                  value={item.note}
                  onChange={(event) => updateItem(index, { note: event.target.value })}
                  disabled={submitting}
                  placeholder="Optional"
                />
              </div>
            </div>
          ))}
        </div>

        <Button size="small" onClick={addItem} disabled={submitting}>
          Add item
        </Button>

        <div className="create-order-preview">
          <Typography.Text type="secondary">Preview only. Backend calculates final totals.</Typography.Text>
          <div className="create-order-preview-grid">
            <OrderField label="Subtotal preview" value={formatMoney(preview.subtotal, draft.currency)} />
            <OrderField label="Total preview" value={formatMoney(preview.total, draft.currency)} />
          </div>
        </div>
      </div>
    </Modal>
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
  orderUpdateError,
  orderUpdating,
  onPageChange,
  onSelectOrder,
  onUpdateOrder,
  onCancelOrder,
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
  orderUpdateError: string | null;
  orderUpdating: boolean;
  onPageChange: (page: number) => void;
  onSelectOrder: (orderUuid: string) => void;
  onUpdateOrder: (orderUuid: string, payload: OrderUpdatePayload) => Promise<void>;
  onCancelOrder: (orderUuid: string, orderNumber: string) => void;
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
                  updateError={orderUpdateError}
                  updating={orderUpdating}
                  onUpdate={onUpdateOrder}
                  onCancel={onCancelOrder}
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
  updateError,
  updating,
  onUpdate,
  onCancel,
  onOpenConversation
}: {
  order: OrderResponse | null;
  loading: boolean;
  error: boolean;
  updateError: string | null;
  updating: boolean;
  onUpdate: (orderUuid: string, payload: OrderUpdatePayload) => Promise<void>;
  onCancel: (orderUuid: string, orderNumber: string) => void;
  onOpenConversation?: (conversationId: string) => void;
}) {
  const [lifecycleDraft, setLifecycleDraft] = useState<OrderLifecycleDraft | null>(null);

  useEffect(() => {
    setLifecycleDraft(order ? buildOrderLifecycleDraft(order) : null);
  }, [order?.payment_status, order?.shipping_status, order?.status, order?.uuid]);

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

  const currentDraft = lifecycleDraft ?? buildOrderLifecycleDraft(order);
  const updatePayload = buildLifecycleUpdatePayload(order, currentDraft);
  const hasChanges = Object.keys(updatePayload).length > 0;
  const isCancelled = order.status === "cancelled";

  return (
    <div className="customer-order-detail">
      <div className="customer-order-detail-grid">
        <OrderField label="Subtotal" value={`${safeText(order.subtotal_amount)} ${safeText(order.currency)}`.trim()} />
        <OrderField label="Discount" value={`${safeText(order.discount_amount)} ${safeText(order.currency)}`.trim()} />
        <OrderField label="Shipping fee" value={`${safeText(order.shipping_fee)} ${safeText(order.currency)}`.trim()} />
        <OrderField label="Total" value={`${safeText(order.total_amount)} ${safeText(order.currency)}`.trim()} />
      </div>

      <section className="customer-order-lifecycle" aria-label="Order lifecycle status">
        <div className="customer-order-lifecycle-grid">
          <div>
            <span className="messenger-profile-label">Order status</span>
            <Select<OrderStatus>
              value={currentDraft.status}
              options={ORDER_LIFECYCLE_STATUS_OPTIONS}
              onChange={(status) => setLifecycleDraft({ ...currentDraft, status })}
              disabled={updating || isCancelled}
              aria-label="Order status"
            />
          </div>
          <div>
            <span className="messenger-profile-label">Payment status</span>
            <Select<PaymentStatus>
              value={currentDraft.payment_status}
              options={PAYMENT_STATUS_OPTIONS}
              onChange={(payment_status) => setLifecycleDraft({ ...currentDraft, payment_status })}
              disabled={updating}
              aria-label="Payment status"
            />
          </div>
          <div>
            <span className="messenger-profile-label">Shipping status</span>
            <Select<ShippingStatus>
              value={currentDraft.shipping_status}
              options={SHIPPING_STATUS_OPTIONS}
              onChange={(shipping_status) => setLifecycleDraft({ ...currentDraft, shipping_status })}
              disabled={updating}
              aria-label="Shipping status"
            />
          </div>
        </div>
        {isCancelled ? (
          <Alert type="warning" showIcon message="This order is cancelled and cannot be reopened." />
        ) : null}
        {updateError ? <Alert type="error" showIcon message={updateError} /> : null}
        <Space wrap>
          <Button
            size="small"
            type="primary"
            loading={updating}
            disabled={!hasChanges || updating}
            onClick={() => void onUpdate(order.uuid, updatePayload)}
          >
            Save statuses
          </Button>
          {!isCancelled ? (
            <Button size="small" danger disabled={updating} onClick={() => onCancel(order.uuid, order.order_number)}>
              Cancel order
            </Button>
          ) : null}
        </Space>
      </section>

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

function buildEmptyOrderItemDraft(): CreateOrderItemDraft {
  return {
    item_name: "",
    sku: "",
    quantity: 1,
    unit_price: 0,
    note: ""
  };
}

function buildOrderLifecycleDraft(order: OrderResponse): OrderLifecycleDraft {
  return {
    status: order.status,
    payment_status: order.payment_status,
    shipping_status: order.shipping_status
  };
}

function buildLifecycleUpdatePayload(
  order: OrderResponse,
  draft: OrderLifecycleDraft
): OrderUpdatePayload {
  const payload: OrderUpdatePayload = {};
  if (order.status !== draft.status) {
    payload.status = draft.status;
  }
  if (order.payment_status !== draft.payment_status) {
    payload.payment_status = draft.payment_status;
  }
  if (order.shipping_status !== draft.shipping_status) {
    payload.shipping_status = draft.shipping_status;
  }
  return payload;
}

function buildEmptyOrderDraft(): CreateOrderDraft {
  return {
    currency: "VND",
    discount_amount: 0,
    shipping_fee: 0,
    shipping_address: "",
    note: "",
    items: [buildEmptyOrderItemDraft()]
  };
}

function validateCreateOrderDraft(draft: CreateOrderDraft): string | null {
  if (draft.items.length === 0) {
    return "Add at least one order item.";
  }
  if (!draft.currency.trim()) {
    return "Currency is required.";
  }
  if (!Number.isFinite(draft.discount_amount) || draft.discount_amount < 0) {
    return "Discount amount cannot be negative.";
  }
  if (!Number.isFinite(draft.shipping_fee) || draft.shipping_fee < 0) {
    return "Shipping fee cannot be negative.";
  }
  for (const [index, item] of draft.items.entries()) {
    if (!item.item_name.trim()) {
      return `Item ${index + 1} needs a name.`;
    }
    if (!Number.isInteger(item.quantity) || item.quantity <= 0) {
      return `Item ${index + 1} quantity must be a whole number greater than 0.`;
    }
    if (!Number.isFinite(item.unit_price) || item.unit_price < 0) {
      return `Item ${index + 1} unit price cannot be negative.`;
    }
  }
  const preview = calculatePreviewTotals(draft);
  if (!Number.isFinite(preview.subtotal) || !Number.isFinite(preview.total)) {
    return "Total preview must be a valid number.";
  }
  if (preview.total < 0) {
    return "Total preview cannot be negative.";
  }
  return null;
}

function calculatePreviewTotals(draft: CreateOrderDraft): { subtotal: number; total: number } {
  const subtotal = draft.items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
  return {
    subtotal,
    total: subtotal - draft.discount_amount + draft.shipping_fee
  };
}

function normaliseOptionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed || null;
}

function normaliseNumberInput(value: number | string | null, fallback: number): number {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function getReadableError(
  error: unknown,
  fallback = "Could not create order. Please check the form and try again."
): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return "Some order fields are invalid. Please review the form and try again.";
    }
  }
  return fallback;
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
